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

    // Track how many terminal rows the live stream occupies so we can erase
    // it before re-rendering with markdown styling. We only consume the
    // terminal width once at the start of the stream — column count rarely
    // changes mid-turn and re-querying per delta is wasteful. If the width
    // probe fails (non-TTY, unusual stream), we leave `term_cols` as None
    // and SKIP the erase entirely (better to see a duplicate than to clobber
    // unrelated scrollback).
    let term_cols: Option<u16> = if render_live {
        crossterm::terminal::size().ok().map(|(c, _)| c)
    } else {
        None
    };
    // Logical column the cursor sits in on the current row. We count
    // newlines as row-consumers explicitly, and wrap when col >= cols.
    let mut cur_col: u32 = 0;
    let mut rows_used: u32 = 0;

    while let Some(item) = stream.next().await {
        match item? {
            ChatStreamEvent::Delta(d) => {
                full.push_str(&d);
                if render_live {
                    let _ = stdout.write_all(d.as_bytes());
                    let _ = stdout.flush();
                    if let Some(cols) = term_cols {
                        let cols_u32 = cols.max(1) as u32;
                        for ch in d.chars() {
                            if ch == '\n' {
                                rows_used = rows_used.saturating_add(1);
                                cur_col = 0;
                            } else if ch == '\r' {
                                cur_col = 0;
                            } else {
                                cur_col += 1;
                                if cur_col >= cols_u32 {
                                    rows_used = rows_used.saturating_add(1);
                                    cur_col = 0;
                                }
                            }
                        }
                    }
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
        // the user immediate feedback; this second pass is the polished view —
        // but the user shouldn't see both. Erase the live stream first.
        if !full.is_empty() {
            if let Some(_cols) = term_cols {
                // Total rows occupied = full rows wrapped + 1 for the current
                // (possibly partial) row, but only if we actually printed
                // anything onto it.
                let total_rows = if cur_col > 0 {
                    rows_used.saturating_add(1)
                } else {
                    rows_used
                };
                // Move to start of current line, then up by (total_rows - 1)
                // so we land on the first row of the stream, then clear from
                // cursor down to the end of the screen. If total_rows is 0
                // (empty stream — shouldn't reach here, full is non-empty)
                // we skip.
                if total_rows > 0 {
                    use crossterm::{cursor, terminal, ExecutableCommand};
                    let up = total_rows.saturating_sub(1);
                    let _ = stdout.execute(cursor::MoveToColumn(0));
                    if up > 0 {
                        // MoveUp takes u16; clamp to avoid overflow on
                        // pathologically long streams.
                        let up_u16: u16 = up.min(u16::MAX as u32) as u16;
                        let _ = stdout.execute(cursor::MoveUp(up_u16));
                    }
                    let _ = stdout.execute(terminal::Clear(
                        terminal::ClearType::FromCursorDown,
                    ));
                    let _ = stdout.flush();
                }
                render_markdown(&full);
            } else {
                // Width detection failed: don't risk clobbering scrollback.
                // Fall back to the prior behavior — blank line + markdown
                // below the live stream (visible duplicate, but safe).
                println!();
                render_markdown(&full);
            }
        }
    }
    Ok(full)
}

fn render_markdown(text: &str) {
    let skin = termimad::MadSkin::default();
    skin.print_text(text);
}
