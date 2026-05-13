//! `alpha completions <shell>` — emit shell completion script to stdout.
//!
//! Generates from the live clap definition, so the script reflects every
//! subcommand and flag the binary currently knows about. Users pipe the
//! output into their shell's completion path.

use clap::CommandFactory;
use clap_complete::Shell;

use crate::cli::Cli;
use crate::context::Context;
use crate::output;

#[derive(Debug, clap::Args)]
pub struct CompletionsArgs {
    /// Target shell. One of: bash, zsh, fish, powershell, elvish.
    #[arg(value_enum)]
    pub shell: Shell,
}

pub async fn run(args: CompletionsArgs, ctx: Context) -> anyhow::Result<()> {
    // Authentication isn't required — completions are static + offline.
    let _ = ctx;

    let mut cmd = Cli::command();
    let bin_name = cmd.get_name().to_string();
    clap_complete::generate(args.shell, &mut cmd, bin_name, &mut std::io::stdout());

    // Friendly install hint on stderr so it doesn't pollute the script
    // when users pipe stdout to a file.
    let hint = match args.shell {
        Shell::Bash => "alpha completions bash > /etc/bash_completion.d/alpha   # or ~/.bash_completion",
        Shell::Zsh => {
            "alpha completions zsh > \"${fpath[1]}/_ap\"   # then `autoload -U compinit; compinit`"
        }
        Shell::Fish => "alpha completions fish > ~/.config/fish/completions/alpha.fish",
        Shell::PowerShell => "alpha completions powershell | Out-String | Invoke-Expression",
        Shell::Elvish => "alpha completions elvish > ~/.config/elvish/lib/alpha.elv",
        _ => "see your shell's docs for where to install the script",
    };
    output::info(format!("install hint: {hint}"));
    Ok(())
}
