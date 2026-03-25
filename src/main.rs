mod cli;
mod commands;
mod config;
mod meta;

use anyhow::{Context, Result};
use clap::Parser;
use git2::Repository;

use cli::{Cli, Commands};
use commands::{add, commit, derive, init};

fn main() -> Result<()> {
    let args = Cli::parse();
    let repo = Repository::discover(".").context("Not in a git repository")?;

    match args.command {
        Commands::Init => {
            init::run(&repo).context("Failed to initialize varcs support")?;
        }
        Commands::Add { files, feature } => {
            add::run(&repo, &files, &feature).context("Failed staging files with meta")?;
        }
        Commands::Commit { message } => {
            commit::run(&repo, &message).context("Failed commiting current index")?;
        }
        Commands::Derive { name } => {
            derive::run(&repo, &name)
                .with_context(|| format!("Failed to derive variant '{}'", name))?;
        }
    }
    Ok(())
}
