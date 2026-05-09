//! `agentprovision logout` — clear the keychain entry.

use crate::context::Context;
use crate::output;

pub async fn run(ctx: Context) -> anyhow::Result<()> {
    ctx.token_store.clear()?;
    if ctx.json {
        let payload = serde_json::json!({
            "logged_out": true,
            "token_store": ctx.token_store_kind.human(),
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
    } else {
        output::ok(format!(
            "Logged out. Token removed from {}.",
            ctx.token_store_kind.human()
        ));
    }
    Ok(())
}
