use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow};
use git2::{BlameOptions, Oid, Repository, Signature, Status, TreeWalkResult};
use regex::Regex;

use crate::config::{Variant, read_config};

pub fn run(repo: &Repository, name: &str) -> Result<()> {
    let statuses = repo.statuses(None)?;
    for entry in statuses.iter() {
        let s = entry.status();
        if s != Status::CURRENT {
            println!("Repository is not clean!");
            return Ok(());
        }
    }

    let variant_spec = get_variant_spec(repo, name).context("Failed to get variant spec")?;
    let target_features: HashSet<String> = variant_spec.features.iter().cloned().collect();
    let ref_name = format!("refs/heads/variant/{}", variant_spec.name);
    let sig = repo.signature()?;
    let variant_head_oid = create_variant_initial_commit(repo, &ref_name, &sig)?;

    let head = repo.head()?;
    let tree = head.peel_to_tree()?;

    let mut tree_builder = repo.treebuilder(None)?;

    tree.walk(git2::TreeWalkMode::PreOrder, |root, entry| {
        if let Some(name) = entry.name() {
            let path = Path::new(root).join(name);
            let content = process_file(repo, &path, &target_features).unwrap();

            let oid = repo.blob(content.as_bytes()).unwrap();
            tree_builder.insert(path, oid, 0o100644).unwrap();
        }
        TreeWalkResult::Ok
    })?;

    let variant_tree_oid = tree_builder.write()?;
    let variant_tree = repo.find_tree(variant_tree_oid)?;
    let variant_parent = repo.find_commit(variant_head_oid)?;

    repo.commit(
        Some(&ref_name),
        &sig,
        &sig,
        &format!(
            "variant derivation with features {:?}",
            variant_spec.features
        ),
        &variant_tree,
        &[&variant_parent],
    )?;
    Ok(())
}

fn get_variant_spec(repo: &Repository, name: &str) -> Result<Variant> {
    let config = read_config(repo)?;
    let variant = config
        .variants
        .get(name)
        .ok_or_else(|| anyhow!("no variant found with name '{}'", name))?;
    Ok(variant.clone())
}

fn create_variant_initial_commit(
    repo: &Repository,
    ref_name: &str,
    sig: &Signature,
) -> Result<Oid> {
    let tree_oid = repo
        .treebuilder(None)?
        .write()
        .context("Failed to create empty tree.")?;
    let tree = repo.find_tree(tree_oid)?;

    let variant_head_oid = repo
        .commit(
            Some(ref_name),
            sig,
            sig,
            "Variant initial commit\n",
            &tree,
            &[],
        )
        .context("Failed to create initial commit for variant")?;
    Ok(variant_head_oid)
}

fn process_file(
    repo: &Repository,
    name: &PathBuf,
    target_features: &HashSet<String>,
) -> Result<String> {
    let file = File::open(name)?;
    let reader = BufReader::new(file);
    let mut lines: Vec<String> = reader.lines().collect::<Result<_, _>>()?;

    let mut commit_cache: HashMap<Oid, bool> = HashMap::new();

    let mut blame_opts = BlameOptions::new();
    let blame = repo.blame_file(Path::new(name), Some(&mut blame_opts))?;

    for (i, line) in lines.iter_mut().enumerate() {
        let line_no = i + 1;

        let hunk = blame
            .get_line(line_no)
            .context("Cant get line info in hunk")?;

        let oid = hunk.final_commit_id();

        let contains_feature = commit_cache.entry(oid).or_insert_with(|| {
            let commit = repo.find_commit(oid).unwrap();
            let summary = commit.body().unwrap();
            extract_feature_meta(summary).is_some_and(|feature| target_features.contains(feature))
        });

        if !*contains_feature {
            *line = String::new();
        }
    }

    // lines.retain(|line| !line.is_empty());
    Ok(lines.join("\n"))
}

// TODO: building each time can be expensive. Look for an alternative
fn extract_feature_meta(commit: &str) -> Option<&str> {
    let re = Regex::new(r"(?m)^FEATURE:\s*(?P<feature>[^\n]+)$").unwrap();
    re.captures(commit)
        .and_then(|caps| caps.name("feature").map(|m| m.as_str()))
}

#[cfg(test)]
mod tests {
    use super::extract_feature_meta;

    #[test]
    fn extracts_feature_when_present() {
        let msg = "chore: init\n\nFeature: core";
        assert_eq!(extract_feature_meta(msg), Some("core"));
    }

    #[test]
    fn extracts_feature_with_other_metadata() {
        let msg = "\
chore: initialize fog support in repo

ChangeId: de9378ec963973b367aa0ad706fa006af3ce65da
Feature: core";
        assert_eq!(extract_feature_meta(msg), Some("core"));
    }

    #[test]
    fn returns_none_when_no_feature() {
        let msg = "fix: missing semicolon";
        assert_eq!(extract_feature_meta(msg), None);
    }

    #[test]
    fn ignores_invalid_format() {
        let msg = "Feature core";
        assert_eq!(extract_feature_meta(msg), None);
    }
}
