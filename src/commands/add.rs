use std::path::Path;

use anyhow::{Context, Result};
use git2::Repository;

use crate::meta::{read_meta, write_meta};

pub fn run(repo: &Repository, files: &[String], feature: &str) -> Result<()> {
    let feature_meta_path = repo.path().join("varcs").join("FEATUREMETA");
    let current_index_feature = read_meta(&feature_meta_path).unwrap_or_default();

    if current_index_feature.is_empty() {
        write_meta(&feature_meta_path, feature)?;
    } else if feature != current_index_feature {
        eprintln!(
            "Current index is already associated with feature '{}'. Commit it before continuing.",
            current_index_feature
        );
        return Ok(());
    }

    let mut index = repo.index()?;
    for file in files {
        index
            .add_path(Path::new(file))
            .with_context(|| format!("Failed to stage path '{}'", file))?;
    }
    index.write()?;

    Ok(())
}
