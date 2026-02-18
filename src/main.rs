mod cli;
mod commands;

use anyhow::{Context, Result};
use clap::Parser;
use git2::Repository;

use cli::{Cli, Commands};
use commands::init;

fn main() -> Result<()> {
    let args = Cli::parse();
    let repo = Repository::discover(".").context("Not in a git repository")?;

    match args.command {
        Commands::Init => {
            init::run(&repo).context("Failed to initialize varcs support")?;
        }
    }
    Ok(())
}
