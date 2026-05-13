//! Tiny "Luna is thinking…" spinner shown while the assistant is computing.
//!
//! Goal: parity with Claude Code / Codex CLI — the moment a user submits
//! a prompt in `alpha chat repl` (or `alpha chat send` foreground),
//! something animates so the terminal doesn't look frozen. The spinner
//! disappears the instant the first stream token lands or the
//! non-streaming reply returns.
//!
//! Why a dedicated module: the spinner has to play nicely with our own
//! stdout writes during streaming (the streaming code writes deltas
//! directly to stdout, then later erases and re-renders with markdown).
//! Centralising the draw-target choice (stderr, not stdout) and the
//! TTY-detection guard here means callers can't accidentally double-
//! suppress or double-render it.
//!
//! Behaviour matrix:
//!   ctx.json        → no spinner (matches `repl()`'s json-bail and keeps
//!                     stderr clean for `chat send --json` callers piping
//!                     stdout to jq while leaving stderr on a TTY)
//!   stdout not TTY  → no spinner (piped to a file / another command)
//!   otherwise       → ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ braille frame at 80ms with a dim suffix
//!
//! Frame count diverges deliberately from `login.rs` / `quickstart.rs`
//! (which include a trailing blank "breath" frame): the chat spinner
//! sits inline with prose deltas, so a continuous 10-frame cycle reads
//! as a single ongoing action rather than a paused-then-resume rhythm.

use std::time::Duration;

use indicatif::{ProgressBar, ProgressDrawTarget, ProgressStyle};

// 10-frame braille cycle. See `frame_count_matches_braille_cycle` test
// + module-level doc for why this diverges from the rest of the CLI.
const FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

const TICK_MS: u64 = 80;

/// Spinner handle. `finish()` clears the line; dropping without calling
/// `finish()` also clears (via Drop) so error paths don't leave the
/// braille frame behind.
///
/// Backed by an indicatif-internal `std::thread` ticker, **not** a tokio
/// task — independent of runtime suspension at `await` points, and
/// joined on `finish_and_clear` / `Drop`. A runtime shutdown
/// (`tokio::main` returning) does not orphan the ticker because either
/// the explicit `.finish()` ran or the value dropped during unwind.
pub struct Thinking(Option<ProgressBar>);

impl Thinking {
    /// Start a spinner unless the caller is in JSON mode or stdout isn't
    /// a TTY. Pass the message the user should see ("Luna is thinking…",
    /// "dispatching…", etc.).
    pub fn start(message: &str, json_mode: bool) -> Self {
        // Skip when output would be redirected anywhere a spinner would
        // be noise — including json envelopes and pipes.
        if json_mode || !console::Term::stdout().is_term() {
            return Thinking(None);
        }

        let pb = ProgressBar::new_spinner();
        // Draw on stderr so the streaming path (which writes deltas to
        // stdout directly with std::io::Write) can keep stdout exclusive.
        // Without this, indicatif's own buffer fights with our prints.
        pb.set_draw_target(ProgressDrawTarget::stderr());

        // `unwrap_or_else` keeps this infallible — a malformed template
        // string is a programmer bug at compile time, not a runtime
        // failure worth bailing on for the user.
        let style = ProgressStyle::with_template("{spinner:.cyan} {msg:.dim}")
            .unwrap_or_else(|_| ProgressStyle::default_spinner())
            .tick_strings(FRAMES);
        pb.set_style(style);
        pb.set_message(message.to_string());
        pb.enable_steady_tick(Duration::from_millis(TICK_MS));

        Thinking(Some(pb))
    }

    /// Clear the spinner line. Idempotent — safe to call twice.
    pub fn finish(&mut self) {
        if let Some(pb) = self.0.take() {
            pb.finish_and_clear();
        }
    }
}

impl Drop for Thinking {
    fn drop(&mut self) {
        // Belt-and-suspenders: if a caller errors out before reaching
        // .finish(), Drop still clears the line so the user isn't left
        // staring at a frozen braille glyph.
        self.finish();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_mode_suppresses_spinner() {
        // The critical guard: in --json mode the spinner MUST be a
        // no-op, otherwise it leaks ANSI to stderr that, while
        // technically separate from the JSON stdout envelope, still
        // confuses scripts that read both streams together.
        let t = Thinking::start("anything", /*json_mode=*/ true);
        assert!(t.0.is_none(), "json_mode should suppress the ProgressBar");
    }

    #[test]
    fn finish_is_idempotent() {
        // Drop also calls finish — calling it explicitly first must
        // not panic on the second (Drop-triggered) invocation.
        //
        // Note: this test exercises the None branch only (the test
        // env isn't a TTY). The Some branch path is exercised
        // manually via `alpha chat repl` and asserted by the round-1
        // code review against indicatif 0.17's panic-safe Drop impl.
        let mut t = Thinking::start("x", /*json_mode=*/ true);
        t.finish();
        t.finish();
        // Drop fires here when `t` goes out of scope — third call.
    }

    #[test]
    fn drop_without_explicit_finish_does_not_panic() {
        // Belt-and-suspenders for the panic-unwind / `?` error path:
        // a caller that bails before reaching `.finish()` relies on
        // Drop to clear the line. Reaching the assertion below proves
        // Drop completed without panicking.
        {
            let _t = Thinking::start("anything", /*json_mode=*/ true);
        } // Drop fires here.
          // If we got here, Drop didn't panic.
    }

    #[test]
    fn frame_count_matches_braille_cycle() {
        // 10-frame braille cycle is a documented contract — if someone
        // adds a frame, the tick period needs to be revisited or the
        // animation looks too fast. Make the dependency explicit.
        assert_eq!(FRAMES.len(), 10);
    }
}
