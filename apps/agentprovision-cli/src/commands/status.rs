//! `agentprovision status` — show the current user, tenant, and server.

use serde::Serialize;

use crate::context::Context;

#[derive(Serialize)]
struct Status {
    server: String,
    cli_version: &'static str,
    authenticated: bool,
    user: Option<UserSummary>,
}

#[derive(Serialize)]
struct UserSummary {
    id: String,
    email: String,
    full_name: Option<String>,
    tenant_id: Option<String>,
    is_superuser: bool,
}

pub async fn run(ctx: Context) -> anyhow::Result<()> {
    let authenticated = ctx.client.token().is_some();
    let user = if authenticated {
        match ctx.client.current_user().await {
            Ok(u) => Some(UserSummary {
                id: u.id.to_string(),
                email: u.email,
                full_name: u.full_name,
                tenant_id: u.tenant_id.map(|x| x.to_string()),
                is_superuser: u.is_superuser,
            }),
            Err(_) => None,
        }
    } else {
        None
    };

    let payload = Status {
        server: ctx.server.clone(),
        cli_version: env!("CARGO_PKG_VERSION"),
        authenticated: user.is_some(),
        user,
    };

    crate::output::emit(ctx.json, &payload, |s| {
        let style_h = |t: &str| console::style(t).bold().to_string();
        println!("{}: {}", style_h("server"), s.server);
        println!("{}: {}", style_h("cli"), s.cli_version);
        println!(
            "{}: {}",
            style_h("authenticated"),
            if s.authenticated { "yes" } else { "no" }
        );
        if let Some(u) = &s.user {
            println!(
                "{}: {} <{}>",
                style_h("user"),
                u.full_name.clone().unwrap_or_else(|| "—".into()),
                u.email
            );
            println!(
                "{}: {}",
                style_h("tenant"),
                u.tenant_id.clone().unwrap_or_else(|| "—".into())
            );
        }
    });
    Ok(())
}
