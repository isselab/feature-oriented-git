use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(version, about)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Initialize variation management support in the git repository
    Init,
    /// Associate feature metadata and stage files to the git index
    Add {
        /// Files to tag with feature meta and stage to git
        files: Vec<String>,
        /// Feature to associate the file(s) with
        #[arg(short, long)]
        feature: String,
    },
    /// Commit staged changes with feature metadata
    Commit {
        /// Commit message
        #[arg(short, long)]
        message: String,
    },
    /// Checkout a variant with the features specified in fog.toml
    Checkout {
        /// Name of the variant entry in fog.toml
        name: String,
        /// Refresh the variant if it already exists
        #[arg(short, long)]
        refresh: bool,
    },
    /// Reconstruct the full file from the edited variant view
    Putback {},
}
