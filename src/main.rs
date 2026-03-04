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
    /// Derive a new variant from the specified set of features
    Derive {
        /// The name of the variant
        name: String,
        /// The set of features to use for the derivation
        #[arg(short, long = "feature", required = true)]
        features: Vec<String>,
    },
    /// List the commits exist in the target branch but not in the current branch
    Diff {
        /// The branch to compare against
        target: String,
        /// Swap the current branch and target when computing the diff
        #[arg(short, long)]
        reverse: bool,
    },
    /// List items in the repository
    List {
        #[arg(short, long)]
        /// Type of the item to list
        r#type: commands::list::ItemType,
    },
}

fn main() -> Result<()> {
    let args = Cli::parse();
    let repo = Repository::discover(".").context("Not in a git repository")?;

    match args.command {
        Commands::Init => {
            commands::init(&repo).context("Failed to initialize VMS support")?;
        }
        Commands::Derive { name, features } => {
            commands::derive(&repo, &name, &features).context("Failed to derive variant")?;
        }
        Commands::Diff { target, reverse } => {
            commands::diff(&repo, &target, reverse).context(format!(
                "Failed to diff current branch against '{}'",
                target
            ))?;
        }
        Commands::List { r#type } => {
            commands::list(&repo, r#type).context("Failed to list variants")?
        }
    }
    Ok(())
}
