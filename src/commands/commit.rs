use anyhow::{Context, Result};
use git2::Repository;

use crate::meta::{read_meta, write_meta};

pub fn run(repo: &Repository, message: &str) -> Result<()> {
    let feature_meta_path = repo.path().join("varcs").join("FEATUREMETA");
    let current_index_feature = read_meta(&feature_meta_path).unwrap_or_default();

    if current_index_feature.is_empty() {
        eprintln!("No associated feature metadata. Aborting.");
        return Ok(());
    }

    let mut index = repo.index()?;

    let tree_oid = index
        .write_tree()
        .context("failed to write tree from index")?;
    let tree = repo.find_tree(tree_oid)?;

    let sig = repo
        .signature()
        .context("failed to determine git signature")?;
    index.write()?;

    let parent_commit = match repo.head() {
        Ok(head) => {
            let commit = head
                .peel_to_commit()
                .context("HEAD does not point to a commit")?;
            Some(commit)
        }
        Err(_) => None,
    };

    let meta_msg = format!(
        "{}\n\nCHANGE_ID: {}\nFEATURE: {}\n",
        message, tree_oid, current_index_feature
    );
    match parent_commit {
        Some(parent) => repo.commit(Some("HEAD"), &sig, &sig, &meta_msg, &tree, &[&parent])?,
        None => repo.commit(Some("HEAD"), &sig, &sig, &meta_msg, &tree, &[])?,
    };

    write_meta(&feature_meta_path, "")?;
    Ok(())
}
