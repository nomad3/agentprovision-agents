//! `agentprovision login` — device-flow first, fallback to email/password.

use clap::Args;
use dialoguer::Password;
use indicatif::{ProgressBar, ProgressStyle};

use agentprovision_core::auth::{
    self, complete_device_flow, request_device_code, DevicePollOutcome,
};
use agentprovision_core::error::Error;

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
    let force_password =
        args.password || args.password_stdin || args.password_env.is_some();
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

    ctx.token_store.save(&token)?;
    ctx.client.set_token(Some(token));

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
        output::info("Token saved to OS keychain.");
    }
    Ok(())
}

async fn try_device_flow(ctx: &Context) -> anyhow::Result<String> {
    let code = request_device_code(&ctx.client).await.map_err(|e| match e {
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
    Ok(token.access_token)
}

async fn password_flow(
    ctx: &Context,
    email_arg: Option<&str>,
    password_stdin: bool,
    password_env: Option<&str>,
) -> anyhow::Result<String> {
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
        std::env::var(var)
            .map_err(|_| anyhow::anyhow!("env var {var} not set or not unicode"))?
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
    Ok(token.access_token)
}
