use std::fs;
use std::path::PathBuf;

use anyhow::Result;

pub fn read_meta(path: &PathBuf) -> Result<String> {
    let data = fs::read_to_string(path)?;
    Ok(data)
}

pub fn write_meta(path: &PathBuf, content: &str) -> Result<()> {
    fs::write(path, content)?;
    Ok(())
}
