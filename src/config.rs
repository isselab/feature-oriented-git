use std::collections::HashMap;
use std::fs;

use anyhow::{Context, Result};
use git2::Repository;
use serde::Deserialize;

#[derive(Deserialize)]
pub struct Config {
    pub variants: HashMap<String, Variant>,
}

#[derive(Deserialize, Clone)]
pub struct Variant {
    pub name: String,
    pub features: Vec<String>,
}

pub fn read_config(repo: &Repository) -> Result<Config> {
    let base_path = repo
        .path()
        .parent()
        .context("Repository has no parent directory")?;
    let config_path = base_path.join("varcs.toml");
    let data = fs::read_to_string(config_path)?;
    let config = toml::from_str(&data)?;
    Ok(config)
}
