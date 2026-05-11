//! Pretty-vs-JSON output helper.
//!
//! Every subcommand calls into here so `--json` works uniformly.

use serde::Serialize;

// `?Sized` lets callers pass slice borrows like `&[KnowledgeEntity]` without
// going through `.to_vec()` first — Serialize is implemented for `[T]` so
// `serde_json` works fine, the default `Sized` bound was the only thing
// blocking it.
pub fn emit<T: Serialize + ?Sized>(json: bool, value: &T, pretty: impl FnOnce(&T)) {
    if json {
        match serde_json::to_string_pretty(value) {
            Ok(s) => println!("{s}"),
            Err(e) => eprintln!("error serialising json: {e}"),
        }
    } else {
        pretty(value);
    }
}

pub fn ok(msg: impl AsRef<str>) {
    eprintln!("{} {}", console::style("ok").green().bold(), msg.as_ref());
}

pub fn info(msg: impl AsRef<str>) {
    eprintln!("{} {}", console::style("•").cyan().bold(), msg.as_ref());
}

pub fn warn(msg: impl AsRef<str>) {
    eprintln!("{} {}", console::style("!").yellow().bold(), msg.as_ref());
}
