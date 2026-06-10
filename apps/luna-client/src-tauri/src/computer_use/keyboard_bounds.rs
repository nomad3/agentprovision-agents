//! Phase 4 keyboard-canary input bounds (pure).
//!
//! The keyboard canary may type a bounded plain-text string and send a small
//! allowlisted set of safe key chords. This module owns those bounds as pure,
//! exhaustively-testable logic: nothing here posts a synthetic key event.
//! Excluded by construction: password/secure fields (handled by the boundary's
//! secure-input gate), arbitrary shell hotkeys, destructive global shortcuts,
//! clipboard injection.

/// Max characters the canary will type in one action.
pub const KEYBOARD_CANARY_MAX_TEXT_LEN: usize = 256;

/// Allowlisted key chords — navigation/selection only. Deliberately NO
/// Cmd/Ctrl/Alt app-command chords and no destructive shortcuts: the canary
/// proves bounded synthetic input, not arbitrary hotkey automation.
pub const KEYBOARD_CHORD_ALLOWLIST: &[&str] = &[
    "left",
    "right",
    "up",
    "down",
    "shift+left",
    "shift+right",
    "shift+up",
    "shift+down",
    // The SEND / submit key — lets Luna complete a "type a message + send" flow in
    // an allowlisted app (e.g. WhatsApp). Still bounded by every actuation gate
    // (allowlisted target + approval grant + signed envelope + frontmost/target-
    // window + secure-input). Mirrors the server _KEYBOARD_CHORD_ALLOWLIST.
    "enter",
];

/// A typed string is in-bounds when it is non-empty, within the length cap, and
/// contains no control characters (so no newline/tab/escape that could submit a
/// form or trigger an action — plain printable text only).
pub fn text_within_bounds(text: &str) -> bool {
    let len = text.chars().count();
    len > 0 && len <= KEYBOARD_CANARY_MAX_TEXT_LEN && !text.chars().any(|c| c.is_control())
}

/// Normalize a chord (list of key tokens) to a canonical `mods+key` string:
/// lowercase, modifier aliases folded (control→ctrl, command/meta→cmd,
/// option→alt), modifiers sorted + deduped first, the single non-modifier key
/// last, joined with `+`. Arrow aliases (`arrowleft`/`leftarrow`) fold to the
/// bare direction. Returns an empty string if there is no single main key.
pub fn normalize_chord(keys: &[String]) -> String {
    let mut mods: Vec<String> = Vec::new();
    let mut main: Option<String> = None;
    for raw in keys {
        let k = raw.trim().to_lowercase();
        match k.as_str() {
            "shift" => mods.push("shift".to_string()),
            "ctrl" | "control" => mods.push("ctrl".to_string()),
            "alt" | "option" | "opt" => mods.push("alt".to_string()),
            "cmd" | "command" | "meta" | "super" | "win" => mods.push("cmd".to_string()),
            "" => {}
            other => {
                // Only one non-modifier key is permitted; a second makes the
                // chord un-normalizable (returns empty → not allowlisted).
                let key = fold_key_alias(other);
                if main.is_some() {
                    return String::new();
                }
                main = Some(key);
            }
        }
    }
    let Some(main) = main else {
        return String::new();
    };
    mods.sort();
    mods.dedup();
    let mut parts = mods;
    parts.push(main);
    parts.join("+")
}

fn fold_key_alias(key: &str) -> String {
    match key {
        "arrowleft" | "leftarrow" => "left".to_string(),
        "arrowright" | "rightarrow" => "right".to_string(),
        "arrowup" | "uparrow" => "up".to_string(),
        "arrowdown" | "downarrow" => "down".to_string(),
        "return" | "enter" => "enter".to_string(),
        other => other.to_string(),
    }
}

/// True when the chord is on the safe allowlist.
pub fn chord_allowed(keys: &[String]) -> bool {
    let normalized = normalize_chord(keys);
    !normalized.is_empty() && KEYBOARD_CHORD_ALLOWLIST.contains(&normalized.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn text_bounds_accept_plain_reject_empty_long_and_control() {
        assert!(text_within_bounds("hello world"));
        assert!(text_within_bounds(&"a".repeat(KEYBOARD_CANARY_MAX_TEXT_LEN)));
        assert!(!text_within_bounds("")); // empty
        assert!(!text_within_bounds(&"a".repeat(KEYBOARD_CANARY_MAX_TEXT_LEN + 1))); // too long
        assert!(!text_within_bounds("line1\nline2")); // newline (control)
        assert!(!text_within_bounds("tab\there")); // tab (control)
        assert!(!text_within_bounds("esc\u{1b}")); // escape (control)
    }

    #[test]
    fn normalize_folds_modifiers_and_arrow_aliases() {
        assert_eq!(normalize_chord(&v(&["left"])), "left");
        assert_eq!(normalize_chord(&v(&["Shift", "Left"])), "shift+left");
        assert_eq!(normalize_chord(&v(&["ArrowLeft"])), "left");
        assert_eq!(normalize_chord(&v(&["Command", "a"])), "cmd+a");
        assert_eq!(normalize_chord(&v(&["control", "c"])), "ctrl+c");
        // two non-modifier keys -> un-normalizable
        assert_eq!(normalize_chord(&v(&["a", "b"])), "");
        // no main key -> empty
        assert_eq!(normalize_chord(&v(&["shift"])), "");
    }

    #[test]
    fn chord_allowlist_accepts_navigation_and_send_rejects_commands() {
        assert!(chord_allowed(&v(&["left"])));
        assert!(chord_allowed(&v(&["shift", "right"])));
        assert!(chord_allowed(&v(&["ArrowDown"])));
        // The SEND key — bare enter (and the `return` alias) is allowlisted.
        assert!(chord_allowed(&v(&["enter"])));
        assert!(chord_allowed(&v(&["Return"])));
        // App/destructive command chords are rejected.
        assert!(!chord_allowed(&v(&["cmd", "q"]))); // quit
        assert!(!chord_allowed(&v(&["cmd", "w"]))); // close
        assert!(!chord_allowed(&v(&["ctrl", "c"])));
        assert!(!chord_allowed(&v(&["cmd", "left"]))); // cmd+arrow not allowlisted
        assert!(!chord_allowed(&v(&["shift", "enter"]))); // newline, not send — rejected
        assert!(!chord_allowed(&v(&["shift"]))); // no main key
    }

    #[test]
    fn normalize_folds_return_to_enter() {
        assert_eq!(normalize_chord(&v(&["enter"])), "enter");
        assert_eq!(normalize_chord(&v(&["Return"])), "enter");
    }
}
