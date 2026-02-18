use anyhow::{Context, Result};
use git2::Repository;
use std::fs;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

pub fn init(repo: &Repository) -> Result<()> {
    let pre_commit_file_template = include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/src/templates/hooks/prepare-commit-msg"
    ));
    let base_path = repo
        .path()
        .parent()
        .context("Repository has no parent directory")?;
    let config_path = base_path.join("varcs.toml");

    if config_path.exists() {
        println!("Config file already exists. Skipping...");
    } else {
        fs::File::create(config_path).context("Failed to create config file")?;
    }

    let hooks_folder = base_path.join(".git/hooks/");
    let target_pc_file = hooks_folder.join("prepare-commit-msg");
    if target_pc_file.exists() {
        println!("Pre-commit file already exists. You may want to update it manually.");
    } else {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o755)
            .open(&target_pc_file)
            .context("Faild to create pre-commit file")?;
        file.write_all(pre_commit_file_template.as_bytes())
            .context("Failed to write to pre-commit file")?;
    }
    Ok(())
}
