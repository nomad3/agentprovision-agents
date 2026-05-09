//! Pretty-vs-JSON output helper.
//!
//! Every subcommand calls into here so `--json` works uniformly.

use serde::Serialize;

pub fn emit<T: Serialize>(json: bool, value: &T, pretty: impl FnOnce(&T)) {
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
