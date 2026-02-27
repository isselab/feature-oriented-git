use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use git2::Repository;

use git_varcs::commands;

#[derive(Parser)]
#[command(name = "git-vms", version)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Initialize variant management support in the git repository
    Init,
    /// List the commits exist in the target branch but not in the current branch
    Diff {
        /// The branch to compare against
        target: String,
        /// Swap the current branch and target when computing the diff
        #[arg(short, long)]
        reverse: bool,
    },
}

fn main() -> Result<()> {
    let args = Cli::parse();
    let repo = Repository::discover(".").context("Not in a git repository")?;

    match args.command {
        Commands::Init => {
            commands::init(&repo).context("Failed to initialize VMS support")?;
        }
        Commands::Diff { target, reverse } => {
            commands::diff(&repo, &target, reverse).context(format!(
                "Failed to diff current branch against '{}'",
                target
            ))?;
        }
    }
    Ok(())
}
