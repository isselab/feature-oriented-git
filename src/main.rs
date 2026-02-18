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
}

fn main() -> Result<()> {
    let args = Cli::parse();
    let repo = Repository::discover(".").context("Not in a git repository")?;

    match args.command {
        Commands::Init => {
            commands::init(&repo).context("Failed to initialize VMS support")?;
        }
    }
    Ok(())
}
