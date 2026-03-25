use std::fs;
use std::io::Write;

use anyhow::{Context, Result};
use git2::Repository;

const DEFAULT_CONFIG: &str = r#"# git-varcs configuration file
# You can define variants and associate features here
"#;

pub fn run(repo: &Repository) -> Result<()> {
    let base_path = repo
        .path()
        .parent()
        .context("Repository has no parent directory")?;
    let config_path = base_path.join("varcs.toml");
    let meta_path = base_path.join(".git/varcs");

    fs::create_dir(meta_path)?;

    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&config_path)
        .with_context(|| format!("Failed to create config file at path: {:?}", config_path))?;

    file.write(DEFAULT_CONFIG.as_bytes())
        .with_context(|| format!("Failed to write default config to: {:?}", config_path))?;

    println!("Initialized config file at {}", config_path.display());
    Ok(())
}
