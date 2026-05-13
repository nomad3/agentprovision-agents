//! `alpha login` — device-flow first, fallback to email/password.

use clap::Args;
use dialoguer::Password;
use indicatif::{ProgressBar, ProgressStyle};

use agentprovision_core::auth::{
    self, complete_device_flow, request_device_code, DevicePollOutcome,
};
use agentprovision_core::error::Error;
use agentprovision_core::models::Token;

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct LoginArgs {
    /// Skip device-flow and prompt for email + password directly.
    #[arg(long)]
    pub password: bool,

    /// Email for password-based login (otherwise prompted).
    #[arg(long)]
    pub email: Option<String>,

    /// Read the password from stdin instead of prompting (useful in scripts / CI).
    #[arg(long, conflicts_with = "password_env")]
    pub password_stdin: bool,

    /// Read the password from the given environment variable.
    #[arg(long, value_name = "VAR")]
    pub password_env: Option<String>,
}

pub async fn run(args: LoginArgs, ctx: Context) -> anyhow::Result<()> {
    let force_password = args.password || args.password_stdin || args.password_env.is_some();
    let token = if force_password {
        password_flow(
            &ctx,
            args.email.as_deref(),
            args.password_stdin,
            args.password_env.as_deref(),
        )
        .await?
    } else {
        match try_device_flow(&ctx).await {
            Ok(t) => t,
            Err(e) => {
                output::warn(format!(
                    "device-flow login unavailable ({e}); falling back to email/password"
                ));
                password_flow(&ctx, args.email.as_deref(), false, None).await?
            }
        }
    };

    // Persist the access token (existing behaviour).
    ctx.token_store.save(&token.access_token)?;
    ctx.client.set_token(Some(token.access_token.clone()));
    // PR `feat(auth): long-lived CLI sessions` — if the server issued
    // a refresh credential, stash it next to the access token so the
    // auto-refresh middleware can swap on 401 without a re-prompt.
    // Older servers (pre-migration 130) leave this null and the CLI
    // falls back to the legacy 7-day forced-relogin behaviour.
    if let Some(rt) = token.refresh_token.as_deref() {
        ctx.token_store.save_refresh(rt)?;
        ctx.client.set_refresh_token(Some(rt.to_string()));
    } else {
        // Defensive: if a prior session left a stale refresh token
        // in the keychain (e.g. server downgraded) drop it now so we
        // don't try to exchange against an endpoint that no longer
        // exists.
        let _ = ctx.token_store.clear_refresh();
    }

    // Pull the current user to confirm the token works and to show identity.
    let me = ctx.client.current_user().await?;
    if ctx.json {
        crate::output::emit(true, &me, |_| {});
    } else {
        let label = me.full_name.clone().unwrap_or_else(|| me.email.clone());
        let tenant = me
            .tenant_id
            .map(|t| t.to_string())
            .unwrap_or_else(|| "—".into());
        output::ok(format!(
            "Logged in as {} ({}), tenant {}",
            label, me.email, tenant
        ));
        output::info(format!("Token saved to {}.", ctx.token_store_kind.human()));
    }

    // PR-Q2: auto-trigger the quickstart flow on first login for an
    // un-onboarded tenant. Silent no-op when the tenant is already
    // onboarded / has deferred / when stdin is non-tty (CI). Failure
    // here never propagates — login succeeded, the onboarding-status
    // probe is informational. JSON mode also suppresses the prompt
    // so scripted callers don't get a Confirm hang.
    if !ctx.json {
        let _ = crate::commands::quickstart::maybe_auto_trigger(&ctx).await;
    }
    Ok(())
}

async fn try_device_flow(ctx: &Context) -> anyhow::Result<Token> {
    let code = request_device_code(&ctx.client)
        .await
        .map_err(|e| match e {
            Error::Api { status, body } => anyhow::anyhow!("HTTP {status}: {body}"),
            other => anyhow::anyhow!(other),
        })?;
    if !ctx.json {
        eprintln!();
        output::info(format!(
            "First copy your one-time code: {}",
            console::style(&code.user_code).bold().yellow()
        ));
        let url = code
            .verification_uri_complete
            .clone()
            .unwrap_or_else(|| code.verification_uri.clone());
        output::info(format!("Then open: {}", console::style(&url).underlined()));
        let _ = webbrowser::open(&url);
    }
    let pb = if ctx.json {
        None
    } else {
        let pb = ProgressBar::new_spinner();
        pb.set_style(
            ProgressStyle::with_template("{spinner:.cyan} waiting for approval...")
                .unwrap()
                .tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ "),
        );
        pb.enable_steady_tick(std::time::Duration::from_millis(120));
        Some(pb)
    };
    let token = complete_device_flow(&ctx.client, &code, |_outcome: &DevicePollOutcome| {})
        .await
        .map_err(|e| anyhow::anyhow!(e))?;
    if let Some(pb) = pb {
        pb.finish_and_clear();
    }
    Ok(token)
}

async fn password_flow(
    ctx: &Context,
    email_arg: Option<&str>,
    password_stdin: bool,
    password_env: Option<&str>,
) -> anyhow::Result<Token> {
    let email = match email_arg {
        Some(e) => e.to_string(),
        None => {
            let theme = dialoguer::theme::ColorfulTheme::default();
            dialoguer::Input::with_theme(&theme)
                .with_prompt("email")
                .interact_text()?
        }
    };
    let password = if let Some(var) = password_env {
        std::env::var(var).map_err(|_| anyhow::anyhow!("env var {var} not set or not unicode"))?
    } else if password_stdin {
        use std::io::BufRead;
        let stdin = std::io::stdin();
        let mut line = String::new();
        stdin.lock().read_line(&mut line)?;
        line.trim_end_matches(['\n', '\r']).to_string()
    } else {
        let theme = dialoguer::theme::ColorfulTheme::default();
        Password::with_theme(&theme)
            .with_prompt("password")
            .interact()?
    };
    let token = auth::login_password(&ctx.client, &email, &password).await?;
    Ok(token)
}
