# Integrations Page Overhaul: OAuth2 + UI Cleanup

## Context

The Integrations page "Skills" tab shows "Skill Configurations" — but these are really integrations/connected apps. Gmail and Google Calendar require manual token entry (no OAuth flow). Peekaboo has no backend. The goal is to make integrations 1-click OAuth connect (like Zapier) and fix the naming.

## Changes Summary

1. Rename "Skills" tab / "Skill Configurations" → "Connected Apps"
2. Remove Peekaboo from registry
3. Add OAuth2 Authorization Code flow for Google (Gmail + Calendar), GitHub, LinkedIn
4. Frontend: 1-click "Connect with Google/GitHub" buttons instead of manual credential forms
5. Update Helm values with OAuth secrets

## Architecture: OAuth2 Popup Flow

```
Frontend                          Backend                         Provider
────────                          ───────                         ────────
Click "Connect with Google"
  → GET /oauth/google/authorize
                                  Generate state JWT (tenant_id,
                                  user_id, nonce, 10min expiry)
                                  Build auth URL with scopes
  ← {auth_url: "https://accounts.google.com/..."}

window.open(auth_url) [popup]
                                                                  User grants access
                                                                  Redirect to callback
                                  GET /oauth/google/callback?code=...&state=...
                                  Verify state JWT
                                  Exchange code for tokens (httpx)
                                  Store access_token + refresh_token
                                    via credential_vault (Fernet encrypted)
                                  Create/enable SkillConfig entries
                                  Return HTML: postMessage('oauth-success') + close

window.addEventListener('message')
  → Refresh integration status
  → Show "Connected" badge
```

## Files to Create/Modify

### 1. NEW: `apps/api/app/api/v1/oauth.py`

OAuth2 router with 4 endpoints:

- `GET /oauth/{provider}/authorize` — Authenticated. Returns auth URL with signed state JWT
- `GET /oauth/{provider}/callback` — Unauthenticated (provider redirect). Exchanges code for tokens, stores encrypted in SkillCredential, returns HTML that posts message to opener
- `POST /oauth/{provider}/disconnect` — Authenticated. Revokes credentials, disables SkillConfig
- `GET /oauth/{provider}/status` — Authenticated. Returns `{connected: bool}` for a provider

Provider config:
```python
OAUTH_PROVIDERS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["gmail.readonly", "gmail.send", "calendar.readonly", "calendar.events"],
        "skill_names": ["gmail", "google_calendar"],  # one OAuth → enables both skills
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user", "read:org"],
        "skill_names": ["github"],
    },
    "linkedin": {
        "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "scopes": ["openid", "profile", "email", "w_member_social"],
        "skill_names": ["linkedin"],
    },
}
```

CSRF protection: `state` param is a signed JWT with `{tenant_id, user_id, provider, nonce, exp}` using existing `SECRET_KEY`.

### 2. MODIFY: `apps/api/app/api/v1/skill_configs.py`

- Remove `peekaboo` entry from `SKILL_CREDENTIAL_SCHEMAS`
- Add `auth_type` and `oauth_provider` fields to each registry entry:
  - `auth_type: "oauth"` for gmail, github, google_calendar, linkedin
  - `auth_type: "manual"` for slack, whatsapp, notion, jira, linear
  - `oauth_provider: "google"` for gmail + google_calendar (shared OAuth)
  - `oauth_provider: "github"` for github
  - `oauth_provider: "linkedin"` for linkedin
- Clear `credentials: []` for OAuth skills (no manual fields needed)
- Update LinkedIn description (remove "browser automation" language)

### 3. MODIFY: `apps/api/app/schemas/skill_config.py`

Add to `SkillRegistryEntry`:
```python
auth_type: str = "manual"              # "manual" | "oauth"
oauth_provider: Optional[str] = None   # "google" | "github" | "linkedin"
```

### 4. MODIFY: `apps/api/app/core/config.py`

Add OAuth settings:
```python
GOOGLE_CLIENT_ID: str | None = None
GOOGLE_CLIENT_SECRET: str | None = None
GOOGLE_REDIRECT_URI: str = "https://servicetsunami.com/api/v1/oauth/google/callback"
GITHUB_CLIENT_ID: str | None = None
GITHUB_CLIENT_SECRET: str | None = None
GITHUB_REDIRECT_URI: str = "https://servicetsunami.com/api/v1/oauth/github/callback"
LINKEDIN_CLIENT_ID: str | None = None
LINKEDIN_CLIENT_SECRET: str | None = None
LINKEDIN_REDIRECT_URI: str = "https://servicetsunami.com/api/v1/oauth/linkedin/callback"
```

### 5. MODIFY: `apps/api/app/api/v1/routes.py`

Mount OAuth router:
```python
from app.api.v1 import oauth
router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
```

### 6. MODIFY: `apps/web/src/components/SkillsConfigPanel.js`

- Rename header "Skill Configurations" → "Connected Apps"
- Change header icon from `FaPuzzlePiece` to `FaPlug`
- Add `useEffect` listener for `window.postMessage` events (`oauth-success`, `oauth-error`)
- Add `oauthStatuses` state, fetch on mount via `GET /oauth/{provider}/status`
- For `auth_type === "oauth"` skills:
  - If not connected: render "Connect with {Provider}" button (opens popup)
  - If connected: render green "Connected" badge + "Disconnect" button
- For `auth_type === "manual"` skills: keep existing credential form behavior
- Add `handleOAuthConnect(provider)` → calls authorize endpoint → `window.open()`
- Add `handleOAuthDisconnect(provider)` → calls disconnect endpoint → refresh
- Handle popup blockers gracefully (show "allow popups" message if `window.open` returns null)

### 7. MODIFY: `apps/web/src/services/skillConfigService.js`

Add methods:
```javascript
oauthAuthorize: (provider) => api.get(`/oauth/${provider}/authorize`),
oauthDisconnect: (provider) => api.post(`/oauth/${provider}/disconnect`),
oauthStatus: (provider) => api.get(`/oauth/${provider}/status`),
```

### 8. MODIFY: `apps/web/src/pages/IntegrationsPage.js`

- Rename "Skills" tab label → "Connected Apps"
- Update page subtitle

### 9. MODIFY: `helm/values/servicetsunami-api.yaml`

Add to `configMap.data`:
```yaml
GOOGLE_REDIRECT_URI: "https://servicetsunami.com/api/v1/oauth/google/callback"
GITHUB_REDIRECT_URI: "https://servicetsunami.com/api/v1/oauth/github/callback"
LINKEDIN_REDIRECT_URI: "https://servicetsunami.com/api/v1/oauth/linkedin/callback"
```

Add to `externalSecret.data`:
```yaml
- secretKey: GOOGLE_CLIENT_ID
  remoteRef: { key: servicetsunami-google-oauth-client-id }
- secretKey: GOOGLE_CLIENT_SECRET
  remoteRef: { key: servicetsunami-google-oauth-client-secret }
- secretKey: GITHUB_CLIENT_ID
  remoteRef: { key: servicetsunami-github-oauth-client-id }
- secretKey: GITHUB_CLIENT_SECRET
  remoteRef: { key: servicetsunami-github-oauth-client-secret }
- secretKey: LINKEDIN_CLIENT_ID
  remoteRef: { key: servicetsunami-linkedin-oauth-client-id }
- secretKey: LINKEDIN_CLIENT_SECRET
  remoteRef: { key: servicetsunami-linkedin-oauth-client-secret }
```

## Implementation Order

1. Remove Peekaboo + add `auth_type`/`oauth_provider` to registry + schema
2. Add OAuth config settings to `config.py`
3. Create `oauth.py` router + mount in `routes.py`
4. Add OAuth service methods to frontend `skillConfigService.js`
5. Rename "Skills" → "Connected Apps" in `IntegrationsPage.js`
6. Overhaul `SkillsConfigPanel.js` with OAuth connect/disconnect flow
7. Update Helm values
8. Create GCP secrets + register Google/GitHub/LinkedIn OAuth apps (manual)
9. Deploy and test

## Manual Setup Required (Post-Deploy)

**Google Cloud Console:**
1. APIs & Services > Credentials > Create OAuth 2.0 Client ID (Web application)
2. Authorized redirect URI: `https://servicetsunami.com/api/v1/oauth/google/callback`
3. Enable Gmail API + Google Calendar API
4. Store client_id/secret in GCP Secret Manager

**GitHub:**
1. Settings > Developer Settings > OAuth Apps > New
2. Callback URL: `https://servicetsunami.com/api/v1/oauth/github/callback`
3. Store client_id/secret in GCP Secret Manager

**LinkedIn:**
1. LinkedIn Developer Portal > Create App
2. Redirect URL: `https://servicetsunami.com/api/v1/oauth/linkedin/callback`
3. Request "Sign in with LinkedIn using OpenID Connect" product
4. Store client_id/secret in GCP Secret Manager

## Reused Infrastructure

- `credential_vault.py` → `store_credential()`, `revoke_credential()` for encrypted token storage
- `SkillConfig` + `SkillCredential` models → no new tables needed
- `jose.jwt` → already in requirements for JWT signing (used for state param)
- `httpx` → already in requirements for async HTTP (used for token exchange)

## Notes

- Google OAuth: one consent screen covers both Gmail and Calendar (shared `oauth_provider: "google"`)
- LinkedIn `w_member_social` scope requires Marketing Developer Platform approval (weeks). V1 may be limited to `openid + profile + email`
- Google sensitive scopes (Gmail) require OAuth consent screen verification for production. Works with test users during dev.
- Token refresh (Google tokens expire in 1h): V1 can refresh on-demand when a 401 is received. No Temporal workflow needed yet.
