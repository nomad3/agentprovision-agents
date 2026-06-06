//! `alpha chat send` (one-shot) and `alpha chat repl`.
//!
//! Chat replies render through `termimad` so code blocks, headers, and lists
//! land nicely in the terminal.
//!
//! The CLI uses the durable async chat-job transport (`/messages/start` +
//! `/jobs/{id}/events`) instead of holding `/messages` or `/messages/stream`
//! open for the full model turn. That keeps every Cloudflare-fronted request
//! short or heartbeat-backed and lets the CLI reconnect by event sequence.

use clap::Args;
use futures_util::StreamExt;
use serde::Serialize;
use std::io::Write;
use std::time::Duration;

use agentprovision_core::chat::{stream_chat_job_events, ChatJobStreamEvent};

use crate::context::Context;
use crate::output;
use crate::thinking::Thinking;

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

    let reply =
        stream_and_collect(&ctx, &session_id, &args.prompt, !ctx.no_stream && !ctx.json).await?;

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
                match stream_and_collect(&ctx, &session_id, trimmed, !ctx.no_stream).await {
                    Ok(reply) => {
                        if ctx.no_stream {
                            render_markdown(&reply);
                        }
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

/// Run a durable async chat job, render chunks live when requested, and
/// re-render with markdown styling on completion.
///
/// Spinner lifecycle (one start, three exits):
///   • start         — top of fn, before `/messages/start` resolves.
///   • first Chunk   — explicit `think.finish()` so the braille glyph
///                     isn't pinned to the line we're about to write.
///   • Done w/o data — explicit `think.finish()` in the terminal arm so a
///                     zero-token reply doesn't leave a frozen frame.
///   • fall-through  — Drop clears on error, panic-unwind, or any
///                     stream that never terminates cleanly.
async fn stream_and_collect(
    ctx: &Context,
    session_id: &str,
    prompt: &str,
    render_live: bool,
) -> anyhow::Result<String> {
    // Spinner covers the gap between durable job dispatch and the first
    // streamed chunk. Cleared on first chunk (below) or on Drop if the
    // stream errors before producing any tokens.
    let mut think = Thinking::start("Luna is thinking…", ctx.json);
    let started = ctx
        .client
        .start_chat_message_job(session_id, prompt)
        .await?;
    let job_id = started.job_id.to_string();
    let mut last_seq = 0_u64;
    let mut full = String::new();
    let mut stdout = std::io::stdout();
    let mut stream_open_failures = 0_u8;
    // When --json or --no-stream is set we MUST NOT write deltas to stdout — they would
    // contaminate the JSON envelope printed at the end (which scripts pipe
    // to jq). Reviewer Important #1 from the PR #332 final review.

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

    loop {
        let mut stream = match stream_chat_job_events(&ctx.client, &job_id, last_seq).await {
            Ok(stream) => {
                stream_open_failures = 0;
                stream
            }
            Err(err) => {
                stream_open_failures = stream_open_failures.saturating_add(1);
                log::warn!("chat job event stream open failed; polling before reconnect: {err}");
                let job = ctx.client.get_chat_job(&job_id).await?;
                match job.status.as_str() {
                    "done" => {
                        if let Some(result_message_id) = job.result_message_id {
                            if let Some(content) = fetch_result_message_content(
                                ctx,
                                session_id,
                                &result_message_id.to_string(),
                            )
                            .await?
                            {
                                think.finish();
                                full = content;
                                break;
                            }
                        }
                        if stream_open_failures >= 3 {
                            anyhow::bail!(
                                "chat job completed, but the event stream could not be replayed"
                            );
                        }
                    }
                    "failed" => {
                        anyhow::bail!(
                            "chat job failed: {}",
                            job.error.unwrap_or_else(|| "unknown error".to_string())
                        );
                    }
                    "cancelled" => anyhow::bail!("chat job was cancelled"),
                    _ => {}
                }
                tokio::time::sleep(Duration::from_secs(1)).await;
                continue;
            }
        };
        let mut reconnect = false;

        while let Some(item) = stream.next().await {
            let event = match item {
                Ok(event) => event,
                Err(err) => {
                    log::warn!("chat job event stream interrupted; reconnecting: {err}");
                    reconnect = true;
                    break;
                }
            };
            match event {
                ChatJobStreamEvent::Chunk { seq, text } => {
                    last_seq = last_seq.max(seq);
                    // First chunk: clear the spinner before printing so
                    // the braille frame doesn't get pinned to the line we're
                    // about to write into. Subsequent calls are no-ops.
                    think.finish();
                    full.push_str(&text);
                    if render_live {
                        let _ = stdout.write_all(text.as_bytes());
                        let _ = stdout.flush();
                        if let Some(cols) = term_cols {
                            let cols_u32 = cols.max(1) as u32;
                            for ch in text.chars() {
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
                ChatJobStreamEvent::Event(event) => {
                    last_seq = last_seq.max(event.seq);
                    // Lifecycle/tool frames are intentionally silent in the
                    // user-facing chat path; they remain available in the
                    // persisted job event log.
                }
                ChatJobStreamEvent::Terminal {
                    status,
                    error,
                    last_seq: terminal_seq,
                    ..
                } => {
                    last_seq = last_seq.max(terminal_seq);
                    think.finish();
                    match status.as_str() {
                        "done" => {
                            reconnect = false;
                            break;
                        }
                        "failed" => {
                            anyhow::bail!(
                                "chat job failed: {}",
                                error.unwrap_or_else(|| "unknown error".to_string())
                            );
                        }
                        "cancelled" => anyhow::bail!("chat job was cancelled"),
                        other => anyhow::bail!("chat job ended with unexpected status: {other}"),
                    }
                }
                ChatJobStreamEvent::Timeout { last_seq: seq } => {
                    last_seq = last_seq.max(seq);
                    reconnect = true;
                    break;
                }
                ChatJobStreamEvent::Truncated { from_seq } => {
                    last_seq = last_seq.max(from_seq);
                    reconnect = true;
                    break;
                }
                ChatJobStreamEvent::Other(_) => {
                    // Ignore unknown frames silently in the user-facing path.
                }
            }
        }

        let job = ctx.client.get_chat_job(&job_id).await?;
        match job.status.as_str() {
            "done" => {
                think.finish();
                break;
            }
            "failed" => {
                anyhow::bail!(
                    "chat job failed: {}",
                    job.error.unwrap_or_else(|| "unknown error".to_string())
                );
            }
            "cancelled" => anyhow::bail!("chat job was cancelled"),
            _ => {
                if !reconnect {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }
        }
    }
    if render_live && !ctx.json {
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
                    let _ = stdout.execute(terminal::Clear(terminal::ClearType::FromCursorDown));
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

async fn fetch_result_message_content(
    ctx: &Context,
    session_id: &str,
    result_message_id: &str,
) -> anyhow::Result<Option<String>> {
    let messages = ctx.client.list_chat_messages(session_id).await?;
    Ok(messages.into_iter().find_map(|message| {
        let id = message.id.map(|id| id.to_string())?;
        if id == result_message_id {
            Some(message.content)
        } else {
            None
        }
    }))
}

fn render_markdown(text: &str) {
    let skin = termimad::MadSkin::default();
    skin.print_text(text);
}
