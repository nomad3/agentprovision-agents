//! `ap chat send` (one-shot) and `ap chat repl`.
//!
//! Streaming chat replies render through `termimad` so code blocks, headers,
//! and lists land nicely in the terminal. With `--no-stream` we POST the
//! non-streaming endpoint and print the assistant message at once.

use clap::Args;
use futures_util::StreamExt;
use serde::Serialize;
use std::io::Write;

use agentprovision_core::chat::{stream_chat, ChatStreamEvent};

use crate::context::Context;
use crate::output;

#[derive(Debug, Args)]
pub struct SendArgs {
    /// The prompt to send.
    #[arg(value_name = "PROMPT")]
    pub prompt: String,

    /// Existing chat session id; if omitted, a fresh session is created.
    #[arg(long)]
    pub session: Option<String>,

    /// Bind a fresh session to a specific agent (UUID). Ignored when --session is given.
    #[arg(long)]
    pub agent: Option<String>,

    /// Optional title for a freshly-created session.
    #[arg(long)]
    pub title: Option<String>,
}

#[derive(Debug, Args)]
pub struct ReplArgs {
    /// Existing chat session id; otherwise a fresh session is created on first message.
    #[arg(long)]
    pub session: Option<String>,

    /// Bind a fresh session to a specific agent (UUID).
    #[arg(long)]
    pub agent: Option<String>,
}

#[derive(Serialize)]
struct SendResult {
    session_id: String,
    reply: String,
}

pub async fn send(args: SendArgs, ctx: Context) -> anyhow::Result<()> {
    let session_id = match args.session.clone() {
        Some(s) => s,
        None => {
            let session = ctx
                .client
                .create_chat_session(args.title.as_deref(), args.agent.as_deref())
                .await?;
            session.id.to_string()
        }
    };

    let reply = if ctx.no_stream {
        let turn = ctx
            .client
            .send_chat_message(&session_id, &args.prompt)
            .await?;
        turn.assistant.content
    } else {
        stream_and_collect(&ctx, &session_id, &args.prompt).await?
    };

    if ctx.json {
        let payload = SendResult { session_id, reply };
        println!("{}", serde_json::to_string_pretty(&payload)?);
    } else if !ctx.no_stream {
        // streaming already printed; just newline
        println!();
    } else {
        // non-streaming: render once
        render_markdown(&reply);
    }
    Ok(())
}

pub async fn repl(args: ReplArgs, ctx: Context) -> anyhow::Result<()> {
    if ctx.json {
        anyhow::bail!("--json is not meaningful for the interactive REPL; use `chat send` instead");
    }
    let session_id = match args.session.clone() {
        Some(s) => s,
        None => {
            let session = ctx
                .client
                .create_chat_session(None, args.agent.as_deref())
                .await?;
            output::info(format!("New chat session: {}", session.id));
            session.id.to_string()
        }
    };

    output::info("Type your message and press Enter. Ctrl-D to exit.");
    let mut rl: rustyline::Editor<(), rustyline::history::FileHistory> = rustyline::Editor::new()?;
    let history_path = dirs::cache_dir().map(|p| p.join("agentprovision").join("repl-history.txt"));
    if let Some(h) = &history_path {
        if let Some(parent) = h.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = rl.load_history(h);
    }

    loop {
        let prompt = format!("{} ", console::style("›").cyan().bold());
        match rl.readline(&prompt) {
            Ok(line) => {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let _ = rl.add_history_entry(trimmed);
                if trimmed == "/exit" || trimmed == "/quit" {
                    break;
                }
                match stream_and_collect(&ctx, &session_id, trimmed).await {
                    Ok(_) => {
                        println!();
                    }
                    Err(e) => {
                        eprintln!("{} {}", console::style("error:").red().bold(), e);
                    }
                }
            }
            Err(rustyline::error::ReadlineError::Eof)
            | Err(rustyline::error::ReadlineError::Interrupted) => break,
            Err(e) => {
                eprintln!("readline: {e}");
                break;
            }
        }
    }
    if let Some(h) = &history_path {
        let _ = rl.save_history(h);
    }
    Ok(())
}

async fn stream_and_collect(
    ctx: &Context,
    session_id: &str,
    prompt: &str,
) -> anyhow::Result<String> {
    let mut stream = stream_chat(&ctx.client, session_id, prompt).await?;
    let mut full = String::new();
    let mut stdout = std::io::stdout();
    // When --json is set we MUST NOT write deltas to stdout — they would
    // contaminate the JSON envelope printed at the end (which scripts pipe
    // to jq). Reviewer Important #1 from the PR #332 final review.
    let render_live = !ctx.json;
    while let Some(item) = stream.next().await {
        match item? {
            ChatStreamEvent::Delta(d) => {
                full.push_str(&d);
                if render_live {
                    let _ = stdout.write_all(d.as_bytes());
                    let _ = stdout.flush();
                }
            }
            ChatStreamEvent::Done => break,
            ChatStreamEvent::Other(_) => {
                // Ignore non-content frames silently in the user-facing path.
            }
        }
    }
    if !ctx.json {
        // Re-render the buffered reply with markdown styling. Streaming gave
        // the user immediate feedback; the second pass is the polished view.
        if !full.is_empty() {
            println!();
            render_markdown(&full);
        }
    }
    Ok(full)
}

fn render_markdown(text: &str) {
    let skin = termimad::MadSkin::default();
    skin.print_text(text);
}
