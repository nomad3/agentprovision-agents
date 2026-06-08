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
use serde::Serialize;
use std::io::Write;
use std::time::Duration;

use agentprovision_core::chat::{
    next_event_before, stream_chat_job_events, ChatJobStreamEvent, NextEvent,
};

use crate::context::Context;
use crate::output;
use crate::thinking::Thinking;

// Transport resilience tuning (PR-A2 items 4 & 5).
/// Base delay for capped-exponential backoff between failed stream-open
/// attempts. Doubles each consecutive failure up to [`STREAM_OPEN_BACKOFF_CAP`].
const STREAM_OPEN_BACKOFF_BASE: Duration = Duration::from_millis(500);
/// Ceiling for the stream-open backoff.
const STREAM_OPEN_BACKOFF_CAP: Duration = Duration::from_secs(8);
/// Bounded retry budget: after this many *consecutive* stream-open failures
/// (with the job not yet terminal) we give up and surface a resumable error
/// instead of reconnecting forever.
const MAX_STREAM_OPEN_FAILURES: u32 = 6;
/// Idle-stall deadline: if no seq-advancing event arrives within this window
/// (measured across reconnects, since the last rendered seq), the job is
/// treated as stalled. The `job_id` stays resumable.
const IDLE_STALL_DEADLINE: Duration = Duration::from_secs(120);

/// Capped-exponential backoff for the Nth (1-based) consecutive failure:
/// `base * 2^(attempt-1)`, clamped to `cap`. The shift is bounded so the
/// multiplier can never overflow for pathological attempt counts.
fn backoff_delay(attempt: u32, base: Duration, cap: Duration) -> Duration {
    let shift = attempt.saturating_sub(1).min(20);
    let mult = 1u128 << shift;
    let ms = base.as_millis().saturating_mul(mult).min(cap.as_millis());
    Duration::from_millis(ms as u64)
}

fn idle_stalled_since(
    now: tokio::time::Instant,
    last_progress: tokio::time::Instant,
    deadline: Duration,
) -> bool {
    now.duration_since(last_progress) >= deadline
}

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
    let mut stream_open_failures = 0_u32;
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

    // Idle-stall deadline anchor (PR-A2 item 5). Declared OUTSIDE the reconnect
    // loop so "idle since last seq" is measured across cooperative reconnects,
    // not reset on every stream re-open. Only seq-advancing events push it.
    let mut last_progress = tokio::time::Instant::now();

    loop {
        if idle_stalled_since(
            tokio::time::Instant::now(),
            last_progress,
            IDLE_STALL_DEADLINE,
        ) {
            think.finish();
            anyhow::bail!(
                "job stalled; no progress in {}s (job_id={job_id}; the job may still be \
                 running; reconnect to resume)",
                IDLE_STALL_DEADLINE.as_secs()
            );
        }

        let mut stream = match stream_chat_job_events(&ctx.client, &job_id, last_seq).await {
            Ok(stream) => {
                stream_open_failures = 0;
                stream
            }
            Err(err) => {
                // A non-retryable open error (auth, 404 job-not-found, malformed
                // request) will never succeed; surface it now, with the
                // resumable job id, rather than burning the retry budget.
                if !err.is_retryable() {
                    think.finish();
                    anyhow::bail!("chat job stream could not be opened (job_id={job_id}): {err}");
                }
                stream_open_failures = stream_open_failures.saturating_add(1);
                log::warn!(
                    "chat job event stream open failed (attempt {stream_open_failures}); \
                     polling job before reconnect: {err}"
                );
                // Poll the snapshot, but TOLERATE a failed poll: the same outage
                // that broke the stream open usually breaks this too, and we must
                // never exit without leaving the user a resumable job id.
                match ctx.client.get_chat_job(&job_id).await {
                    Ok(job) => match job.status.as_str() {
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
                                think.finish();
                                anyhow::bail!(
                                    "chat job completed, but its event stream could not be \
                                     replayed (job_id={job_id})"
                                );
                            }
                        }
                        "failed" => {
                            think.finish();
                            anyhow::bail!(
                                "chat job failed: {}",
                                job.error.unwrap_or_else(|| "unknown error".to_string())
                            );
                        }
                        "cancelled" => {
                            think.finish();
                            anyhow::bail!("chat job was cancelled");
                        }
                        _ => {}
                    },
                    Err(poll_err) => {
                        log::warn!("chat job snapshot poll failed: {poll_err}");
                    }
                }
                // Bounded retry budget: stop reconnecting after too many
                // consecutive open failures and surface a clear, resumable error.
                if stream_open_failures >= MAX_STREAM_OPEN_FAILURES {
                    think.finish();
                    anyhow::bail!(
                        "server unreachable / job stalled after {stream_open_failures} attempts \
                         (job_id={job_id}; the job may still be running; reconnect to resume): {err}"
                    );
                }
                tokio::time::sleep(backoff_delay(
                    stream_open_failures,
                    STREAM_OPEN_BACKOFF_BASE,
                    STREAM_OPEN_BACKOFF_CAP,
                ))
                .await;
                continue;
            }
        };
        let mut reconnect = false;
        // Whether this stream session produced any seq progress, used only to
        // pace reconnects (an empty/dropped stream waits a beat to avoid a hot
        // spin; a productive one re-opens promptly).
        let mut made_progress_this_stream = false;

        loop {
            let deadline = last_progress + IDLE_STALL_DEADLINE;
            let next = match next_event_before(&mut stream, deadline).await {
                Ok(next) => next,
                Err(err) => {
                    if !err.is_retryable() {
                        think.finish();
                        anyhow::bail!("chat job stream error (job_id={job_id}): {err}");
                    }
                    log::warn!("chat job event stream interrupted; reconnecting: {err}");
                    reconnect = true;
                    break;
                }
            };
            let event = match next {
                NextEvent::Event(event) => event,
                NextEvent::Ended => {
                    // Clean close without a terminal frame; reconnect by seq.
                    reconnect = true;
                    break;
                }
                NextEvent::Stalled => {
                    think.finish();
                    anyhow::bail!(
                        "job stalled; no progress in {}s (job_id={job_id}; the job may still be \
                         running; reconnect to resume)",
                        IDLE_STALL_DEADLINE.as_secs()
                    );
                }
            };
            match event {
                ChatJobStreamEvent::Chunk { seq, text } => {
                    last_seq = last_seq.max(seq);
                    last_progress = tokio::time::Instant::now();
                    made_progress_this_stream = true;
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
                    last_progress = tokio::time::Instant::now();
                    made_progress_this_stream = true;
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
                            // reconnect stays false (initializer); the post-loop
                            // snapshot sees "done" and breaks the outer loop.
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
                    // PR-A2 item 6: explicit handling. The server's replay window
                    // no longer covers our cursor; events between last_seq and
                    // from_seq are gone. Warn that some streamed output was
                    // skipped, advance to the server floor, and reconnect. We do
                    // NOT touch `last_progress`; a truncation is not new output.
                    if from_seq > last_seq {
                        log::warn!(
                            "chat job replay window exceeded: skipping events {}..{from_seq} \
                             (job_id={job_id}); some streamed output may be missing",
                            last_seq.saturating_add(1)
                        );
                    }
                    last_seq = last_seq.max(from_seq);
                    reconnect = true;
                    break;
                }
                ChatJobStreamEvent::Other(_) => {
                    // Heartbeat / unknown frame: NOT seq progress, so the idle
                    // deadline is unchanged. Guard against a heartbeat-only
                    // stream masking a real stall; `timeout_at` can return a
                    // ready item even after the deadline has passed.
                    if idle_stalled_since(
                        tokio::time::Instant::now(),
                        last_progress,
                        IDLE_STALL_DEADLINE,
                    ) {
                        think.finish();
                        anyhow::bail!(
                            "job stalled; no progress in {}s (job_id={job_id}; the job may still \
                             be running; reconnect to resume)",
                            IDLE_STALL_DEADLINE.as_secs()
                        );
                    }
                }
            }
        }

        // Snapshot the job to decide terminal vs. reconnect. TOLERATE a failed
        // poll for the same resumability reason as above; the idle-stall
        // deadline (measured across reconnects) is the global backstop that
        // bounds any reconnect spin.
        match ctx.client.get_chat_job(&job_id).await {
            Ok(job) => match job.status.as_str() {
                "done" => {
                    think.finish();
                    break;
                }
                "failed" => {
                    think.finish();
                    anyhow::bail!(
                        "chat job failed: {}",
                        job.error.unwrap_or_else(|| "unknown error".to_string())
                    );
                }
                "cancelled" => {
                    think.finish();
                    anyhow::bail!("chat job was cancelled");
                }
                _ => {
                    // Still running. Re-open promptly after a productive
                    // reconnect; pace empty/dropped streams to avoid a hot spin.
                    if !reconnect || !made_progress_this_stream {
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                }
            },
            Err(poll_err) => {
                log::warn!("chat job snapshot poll failed; will reconnect: {poll_err}");
                tokio::time::sleep(Duration::from_secs(1)).await;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backoff_grows_then_caps() {
        let base = Duration::from_millis(500);
        let cap = Duration::from_secs(8);
        assert_eq!(backoff_delay(1, base, cap), Duration::from_millis(500));
        assert_eq!(backoff_delay(2, base, cap), Duration::from_secs(1));
        assert_eq!(backoff_delay(3, base, cap), Duration::from_secs(2));
        assert_eq!(backoff_delay(4, base, cap), Duration::from_secs(4));
        assert_eq!(backoff_delay(5, base, cap), Duration::from_secs(8));
        // Capped from here on.
        assert_eq!(backoff_delay(6, base, cap), Duration::from_secs(8));
        assert_eq!(backoff_delay(7, base, cap), Duration::from_secs(8));
    }

    #[test]
    fn backoff_never_overflows_for_large_attempts() {
        let base = Duration::from_millis(500);
        let cap = Duration::from_secs(8);
        // Pathological attempt counts must clamp, not panic/overflow.
        assert_eq!(backoff_delay(64, base, cap), cap);
        assert_eq!(backoff_delay(u32::MAX, base, cap), cap);
    }

    #[test]
    fn backoff_attempt_zero_is_base() {
        // Defensive: 1-based callers never pass 0, but it must not underflow.
        let base = Duration::from_millis(500);
        let cap = Duration::from_secs(8);
        assert_eq!(backoff_delay(0, base, cap), base);
    }

    #[test]
    fn idle_stall_deadline_is_inclusive() {
        let now = tokio::time::Instant::now();
        let deadline = Duration::from_secs(120);

        assert!(!idle_stalled_since(now, now, deadline));
        assert!(!idle_stalled_since(
            now,
            now - Duration::from_secs(119),
            deadline
        ));
        assert!(idle_stalled_since(
            now,
            now - Duration::from_secs(120),
            deadline
        ));
        assert!(idle_stalled_since(
            now,
            now - Duration::from_secs(121),
            deadline
        ));
    }
}
