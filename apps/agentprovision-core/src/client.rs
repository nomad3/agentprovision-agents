//! Async HTTP client for the AgentProvision API.
//!
//! Wraps `reqwest::Client` with:
//! * a configured base URL (defaults to `https://agentprovision.com`)
//! * an optional bearer token (set via [`ApiClient::set_token`])
//! * a uniform error model — non-2xx responses become `Error::Api`

use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use reqwest::{Client, Method, RequestBuilder, Response, StatusCode};
use serde::de::DeserializeOwned;
use serde::Serialize;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use url::Url;

use crate::error::{Error, Result};
use crate::models::{
    Agent, ChatMessage, ChatMessageRequest, ChatSession, ChatTurn, DynamicWorkflow,
    DynamicWorkflowRun, IntegrationStatus, Tenant, Token, User, Workflow, WorkflowRun,
    WorkflowRunRequest,
};

pub const DEFAULT_BASE_URL: &str = "https://agentprovision.com";

#[derive(Clone)]
pub struct ApiClient {
    inner: Client,
    base: Url,
    token: Arc<Mutex<Option<String>>>,
    tenant_id: Arc<Mutex<Option<String>>>,
}

impl ApiClient {
    pub fn new(base_url: &str) -> Result<Self> {
        let base = Url::parse(base_url)?;
        let inner = Client::builder()
            // Chat turns can run >60s (agent router → Temporal → MCP → LLM).
            // The streaming SSE endpoints aren't bounded by this timeout
            // because they consume `bytes_stream`, which is fine.
            .timeout(Duration::from_secs(180))
            .user_agent(concat!("agentprovision-core/", env!("CARGO_PKG_VERSION")))
            .build()?;
        Ok(Self {
            inner,
            base,
            token: Arc::new(Mutex::new(None)),
            tenant_id: Arc::new(Mutex::new(None)),
        })
    }

    pub fn with_token(self, token: impl Into<String>) -> Self {
        self.set_token(Some(token.into()));
        self
    }

    pub fn set_token(&self, token: Option<String>) {
        *self.token.lock().expect("token lock") = token;
    }

    pub fn token(&self) -> Option<String> {
        self.token.lock().expect("token lock").clone()
    }

    pub fn set_tenant_id(&self, tenant_id: Option<String>) {
        *self.tenant_id.lock().expect("tenant lock") = tenant_id;
    }

    pub fn base_url(&self) -> &Url {
        &self.base
    }

    pub fn build_url(&self, path: &str) -> Result<Url> {
        // `Url::join` rejects leading slash on relative paths in some cases;
        // strip our leading slash and let the base's path drive the join.
        let trimmed = path.trim_start_matches('/');
        // Ensure the base ends with `/` so `join` treats it as a directory.
        let mut base = self.base.clone();
        if !base.path().ends_with('/') {
            let new_path = format!("{}/", base.path());
            base.set_path(&new_path);
        }
        Ok(base.join(trimmed)?)
    }

    /// Inner `reqwest::Client` accessor for low-level operations
    /// (used by `chat::stream_chat` and `events::tail_session_events` to
    /// open SSE connections that the high-level helpers don't model).
    pub fn http(&self) -> &Client {
        &self.inner
    }

    fn auth_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        if let Some(tok) = self.token() {
            if let Ok(val) = HeaderValue::from_str(&format!("Bearer {tok}")) {
                headers.insert(AUTHORIZATION, val);
            }
        }
        if let Some(tenant) = self.tenant_id.lock().expect("tenant lock").clone() {
            if let Ok(val) = HeaderValue::from_str(&tenant) {
                headers.insert("X-Tenant-Id", val);
            }
        }
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers
    }

    pub fn request(&self, method: Method, path: &str) -> Result<RequestBuilder> {
        let url = self.build_url(path)?;
        let req = self.inner.request(method, url).headers(self.auth_headers());
        Ok(req)
    }

    /// Send a request and decode the JSON response body, mapping non-2xx into
    /// `Error::Api` with the response body included for debugging.
    pub async fn send_json<T: DeserializeOwned>(&self, req: RequestBuilder) -> Result<T> {
        let resp = req.send().await?;
        let resp = self.check_status(resp).await?;
        let bytes = resp.bytes().await?;
        if bytes.is_empty() {
            // Try to coerce empty response into `()` or a default; otherwise
            // fail loud.
            return Err(Error::other("expected JSON response, got empty body"));
        }
        let parsed: T = serde_json::from_slice(&bytes)?;
        Ok(parsed)
    }

    pub async fn send_no_body(&self, req: RequestBuilder) -> Result<()> {
        let resp = req.send().await?;
        let _ = self.check_status(resp).await?;
        Ok(())
    }

    pub async fn check_status(&self, resp: Response) -> Result<Response> {
        let status = resp.status();
        if status.is_success() {
            return Ok(resp);
        }
        if status == StatusCode::UNAUTHORIZED {
            return Err(Error::Unauthorized);
        }
        let body = resp.text().await.unwrap_or_default();
        Err(Error::Api {
            status: status.as_u16(),
            body,
        })
    }

    // ---- High-level endpoints --------------------------------------------------

    /// `POST /api/v1/auth/login` — OAuth2-style form-encoded login.
    /// Returns the access token but does **not** mutate this client's token.
    /// Callers decide whether to persist (CLI: yes, into keychain; ad-hoc: no).
    pub async fn login_password(&self, email: &str, password: &str) -> Result<Token> {
        let url = self.build_url("/api/v1/auth/login")?;
        let req = self
            .inner
            .post(url)
            .form(&[("username", email), ("password", password)]);
        let resp = req.send().await?;
        let resp = self.check_status(resp).await?;
        Ok(resp.json::<Token>().await?)
    }

    /// `GET /api/v1/auth/users/me`
    pub async fn current_user(&self) -> Result<User> {
        let req = self.request(Method::GET, "/api/v1/auth/users/me")?;
        self.send_json(req).await
    }

    /// `GET /api/v1/agents`
    pub async fn list_agents(&self) -> Result<Vec<Agent>> {
        let req = self.request(Method::GET, "/api/v1/agents")?;
        self.send_json(req).await
    }

    /// `GET /api/v1/agents/{agent_id}` — single-agent detail. The backend
    /// returns the same shape as the list endpoint plus runtime fields that
    /// our `Agent` model carries forward-compatibly via `#[serde(default)]`.
    pub async fn get_agent(&self, agent_id: &str) -> Result<Agent> {
        let req = self.request(Method::GET, &format!("/api/v1/agents/{agent_id}"))?;
        self.send_json(req).await
    }

    /// `GET /api/v1/tenants/{id}` — caller must have the id (from the JWT or
    /// `current_user`).
    pub async fn get_tenant(&self, tenant_id: &str) -> Result<Tenant> {
        let req = self.request(Method::GET, &format!("/api/v1/tenants/{tenant_id}"))?;
        self.send_json(req).await
    }

    /// `GET /api/v1/chat/sessions`
    pub async fn list_chat_sessions(&self) -> Result<Vec<ChatSession>> {
        let req = self.request(Method::GET, "/api/v1/chat/sessions")?;
        self.send_json(req).await
    }

    /// `GET /api/v1/chat/sessions/{id}/messages`
    pub async fn list_chat_messages(&self, session_id: &str) -> Result<Vec<ChatMessage>> {
        let req = self.request(
            Method::GET,
            &format!("/api/v1/chat/sessions/{session_id}/messages"),
        )?;
        self.send_json(req).await
    }

    /// `POST /api/v1/chat/sessions` — create a session (optionally bound to an
    /// agent).
    pub async fn create_chat_session(
        &self,
        title: Option<&str>,
        agent_id: Option<&str>,
    ) -> Result<ChatSession> {
        #[derive(Serialize)]
        struct Body<'a> {
            #[serde(skip_serializing_if = "Option::is_none")]
            title: Option<&'a str>,
            #[serde(skip_serializing_if = "Option::is_none")]
            agent_id: Option<&'a str>,
        }
        let req = self
            .request(Method::POST, "/api/v1/chat/sessions")?
            .json(&Body { title, agent_id });
        self.send_json(req).await
    }

    /// `POST /api/v1/chat/sessions/{id}/messages` — non-streaming send.
    pub async fn send_chat_message(&self, session_id: &str, content: &str) -> Result<ChatTurn> {
        let req = self
            .request(
                Method::POST,
                &format!("/api/v1/chat/sessions/{session_id}/messages"),
            )?
            .json(&ChatMessageRequest { content });
        self.send_json(req).await
    }

    /// `GET /api/v1/workflows`
    pub async fn list_workflows(&self) -> Result<Vec<Workflow>> {
        let req = self.request(Method::GET, "/api/v1/workflows")?;
        self.send_json(req).await
    }

    /// `GET /api/v1/workflows/runs/{id}`
    pub async fn get_workflow_run(&self, run_id: &str) -> Result<WorkflowRun> {
        let req = self.request(Method::GET, &format!("/api/v1/workflows/runs/{run_id}"))?;
        self.send_json(req).await
    }

    // ── Dynamic workflows ───────────────────────────────────────────
    // These match the endpoints the web `WorkflowsPage` hits via
    // `apps/web/src/services/dynamicWorkflowService.js`. The legacy
    // `list_workflows` / `get_workflow_run` methods above hit the
    // older `/workflows` summary endpoint and are kept for compatibility.

    /// `GET /api/v1/dynamic-workflows[?status=<state>]`
    pub async fn list_dynamic_workflows(
        &self,
        status: Option<&str>,
    ) -> Result<Vec<DynamicWorkflow>> {
        let mut req = self.request(Method::GET, "/api/v1/dynamic-workflows")?;
        if let Some(s) = status {
            req = req.query(&[("status", s)]);
        }
        self.send_json(req).await
    }

    /// `GET /api/v1/dynamic-workflows/{id}`
    pub async fn get_dynamic_workflow(&self, workflow_id: &str) -> Result<DynamicWorkflow> {
        let req = self.request(
            Method::GET,
            &format!("/api/v1/dynamic-workflows/{workflow_id}"),
        )?;
        self.send_json(req).await
    }

    /// `POST /api/v1/dynamic-workflows/{id}/run`
    ///
    /// `dry_run` mirrors the web TestConsole — the backend validates the
    /// definition without dispatching to Temporal, useful for `ap workflow run
    /// --dry-run` ahead of a real run.
    pub async fn run_dynamic_workflow(
        &self,
        workflow_id: &str,
        input_data: Option<serde_json::Value>,
        dry_run: bool,
    ) -> Result<DynamicWorkflowRun> {
        let body = WorkflowRunRequest {
            input_data,
            dry_run,
        };
        let req = self
            .request(
                Method::POST,
                &format!("/api/v1/dynamic-workflows/{workflow_id}/run"),
            )?
            .json(&body);
        self.send_json(req).await
    }

    /// `GET /api/v1/dynamic-workflows/{id}/runs?limit=N`
    pub async fn list_dynamic_workflow_runs(
        &self,
        workflow_id: &str,
        limit: Option<u32>,
    ) -> Result<Vec<DynamicWorkflowRun>> {
        let mut req = self.request(
            Method::GET,
            &format!("/api/v1/dynamic-workflows/{workflow_id}/runs"),
        )?;
        if let Some(n) = limit {
            req = req.query(&[("limit", n.to_string())]);
        }
        self.send_json(req).await
    }

    /// `GET /api/v1/dynamic-workflows/runs/{run_id}`
    pub async fn get_dynamic_workflow_run(&self, run_id: &str) -> Result<DynamicWorkflowRun> {
        let req = self.request(
            Method::GET,
            &format!("/api/v1/dynamic-workflows/runs/{run_id}"),
        )?;
        self.send_json(req).await
    }

    // ── Integration status ─────────────────────────────────────────
    // Mirrors what the web IntegrationsPage and the workflow
    // activation-gate consume via `dynamicWorkflowService.getIntegrationStatus`.

    /// `GET /api/v1/integrations/status`
    pub async fn list_integration_status(&self) -> Result<Vec<IntegrationStatus>> {
        let req = self.request(Method::GET, "/api/v1/integrations/status")?;
        self.send_json(req).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_url_handles_trailing_and_leading_slashes() {
        let c = ApiClient::new("https://example.com").unwrap();
        let u = c.build_url("/api/v1/auth/users/me").unwrap();
        assert_eq!(u.as_str(), "https://example.com/api/v1/auth/users/me");

        let c2 = ApiClient::new("https://example.com/base").unwrap();
        let u2 = c2.build_url("api/v1/foo").unwrap();
        assert_eq!(u2.as_str(), "https://example.com/base/api/v1/foo");
    }

    #[test]
    fn token_round_trip() {
        let c = ApiClient::new("https://example.com").unwrap();
        assert!(c.token().is_none());
        c.set_token(Some("abc".into()));
        assert_eq!(c.token().as_deref(), Some("abc"));
        c.set_token(None);
        assert!(c.token().is_none());
    }
}
