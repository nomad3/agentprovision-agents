//! `alpha logout` — revoke server-side then clear the keychain.

use serde_json::json;

use crate::context::Context;
use crate::output;

pub async fn run(ctx: Context) -> anyhow::Result<()> {
    // Server-side revocation FIRST. If a stolen refresh token is sitting
    // on this box, wiping the local keychain alone leaves it usable
    // until the 30-day expiry — the whole point of refresh-token
    // rotation in CLI tools is that logout is a hard revocation.
    // Review finding B-3 on PR #442; reviewer IMPORTANT-3 on PR #445
    // switched the call to `post_no_body_json` so we no longer
    // string-match the empty-body decode error.
    let mut server_revoked = false;
    if let Ok(Some(refresh)) = ctx.token_store.load_refresh() {
        // Best-effort: the local keychain wipe below is the
        // authoritative end state — a network failure here shouldn't
        // strand the user logged-in locally. We log via -v for
        // forensic but don't propagate the error.
        let payload = json!({"refresh_token": refresh});
        match ctx
            .client
            .post_no_body_json("/api/v1/auth/token/revoke", &payload)
            .await
        {
            Ok(()) => server_revoked = true,
            Err(e) => log::warn!("alpha logout: server-side revoke failed: {e}"),
        }
    }

    ctx.token_store.clear()?;
    if ctx.json {
        let payload = json!({
            "logged_out": true,
            "server_revoked": server_revoked,
            "token_store": ctx.token_store_kind.human(),
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
    } else {
        let suffix = if server_revoked {
            " and revoked server-side"
        } else {
            ""
        };
        output::ok(format!(
            "Logged out. Token removed from {}{}.",
            ctx.token_store_kind.human(),
            suffix,
        ));
    }
    Ok(())
}
