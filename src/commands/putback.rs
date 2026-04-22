use crate::meta::read_variant_meta;
use anyhow::{Result, anyhow};
use git2::{ObjectType, Repository, TreeWalkMode, TreeWalkResult};
use std::fs;
use std::path::PathBuf;

pub fn run(repo: &Repository) -> Result<()> {
    let meta_store = read_variant_meta(repo).unwrap_or_default();
    let origin = meta_store
        .variants
        .get("simple-calculator")
        .ok_or_else(|| anyhow!("Variant 'simple-calculator' not found"))?;

    let commit = repo.find_commit_by_prefix(&origin.commit)?;
    let tree = commit.tree()?;

    tree.walk(TreeWalkMode::PreOrder, |root, entry| {
        if entry.kind() != Some(ObjectType::Blob) {
            return TreeWalkResult::Ok;
        }

        let Some(name) = entry.name() else {
            return TreeWalkResult::Ok;
        };

        let path = PathBuf::from(format!("{}{}", root, name));

        // Only process files that actually exist in the working directory
        if !path.exists() {
            return TreeWalkResult::Ok;
        }

        let Ok(obj) = entry.to_object(repo) else {
            return TreeWalkResult::Ok;
        };

        let Some(blob) = obj.as_blob() else {
            return TreeWalkResult::Ok;
        };

        if let Err(e) = process_file(&path, blob) {
            eprintln!("Failed to process {:?}: {}", path, e);
        }

        TreeWalkResult::Ok
    })?;

    Ok(())
}

fn process_file(path: &PathBuf, blob: &git2::Blob) -> Result<()> {
    let original_content = std::str::from_utf8(blob.content())?;
    let original_lines: Vec<&str> = original_content.split_terminator('\n').collect();

    let variant_content = fs::read_to_string(path)?;
    let mut reconstructed: Vec<String> = vec![];

    for line in variant_content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("# morph:") {
            if let Some((start, end)) = extract_range(trimmed) {
                // Marker range is 1-based.
                for idx in start..=end {
                    if idx > 0 && idx <= original_lines.len() {
                        reconstructed.push(original_lines[idx - 1].to_string());
                    } else {
                        eprintln!("Warning: Index {} out of range in {:?}", idx, path);
                    }
                }
                continue;
            }
        }

        // Not a marker so keep the line as it is
        reconstructed.push(line.to_string());
    }

    fs::write(path, reconstructed.join("\n"))?;
    Ok(())
}

fn extract_range(trimmed: &str) -> Option<(usize, usize)> {
    // Expected format: "# morph:1-10 hidden feature 'name'"
    let payload = trimmed.strip_prefix("# morph:")?;
    let range_part = payload.split_whitespace().next()?;
    let (start_str, end_str) = range_part.split_once("-")?;

    let start = start_str.parse::<usize>().ok()?;
    let end = end_str.parse::<usize>().ok()?;
    Some((start, end))
}
