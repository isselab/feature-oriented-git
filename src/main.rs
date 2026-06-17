mod cli;
mod commands;
mod config;
mod meta;
mod parser;

use anyhow::{Context, Result};
use clap::Parser;
use git2::Repository;

use cli::{Cli, Commands};
use commands::{add, checkout, commit, init, putback};

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
        Commands::Checkout { name, refresh } => {
            checkout::run(&repo, &name, refresh)
                .with_context(|| format!("Failed to derive variant '{}'", name))?;
        }
        Commands::Putback {} => {
            putback::run(&repo).context("Failed to sync edited view")?;
        }
    }
    Ok(())
}
