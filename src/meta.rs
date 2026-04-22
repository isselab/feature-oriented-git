use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use git2::Repository;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Default)]
pub struct VariantMetaStore {
    pub variants: HashMap<String, VariantMeta>,
}

#[derive(Serialize, Deserialize)]
pub struct VariantMeta {
    pub commit: String,
    pub tree: String,
    pub features: Vec<String>,
    pub created_at: String, // ISO 8601
}

pub fn read_variant_meta(repo: &Repository) -> Result<VariantMetaStore> {
    let base_path = repo.path();
    let meta_path = base_path.join("variant-meta.json");
    let data = fs::read_to_string(meta_path)?;
    let store = serde_json::from_str(&data).context("Failed to deserialize variant meta")?;
    Ok(store)
}

pub fn write_variant_meta(repo: &Repository, store: &VariantMetaStore) -> Result<()> {
    let base_path = repo.path();
    let meta_path = base_path.join("variant-meta.json");
    let data = serde_json::to_string_pretty(&store).context("Failed to serialize variant meta")?;
    fs::write(&meta_path, data)?;
    Ok(())
}

pub fn read_meta(path: &PathBuf) -> Result<String> {
    let data = fs::read_to_string(path)?;
    Ok(data)
}

pub fn write_meta(path: &PathBuf, content: &str) -> Result<()> {
    fs::write(path, content)?;
    Ok(())
}
