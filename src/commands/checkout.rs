use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow};
use chrono::Utc;
use git2::{BlameOptions, Commit, ObjectType, Oid, Repository, Status, Tree};
use regex::Regex;

use crate::meta::{VariantMeta, read_variant_meta, write_variant_meta};
use crate::parser::evaluator::Evaluator;
use crate::parser::grammar::parse_clafer_module;

pub fn run(repo: &Repository, name: &str, refresh: bool) -> Result<()> {
    let statuses = repo.statuses(None)?;
    for entry in statuses.iter() {
        let s = entry.status();
        if s != Status::CURRENT {
            println!("Repository is not clean!");
            return Ok(());
        }
    }

    let features = derive_features(repo, name).context("Failed to derive variant from model")?;
    let ref_name = format!("refs/heads/variant/{}", name);

    let variant_ref = repo.find_reference(&ref_name).ok();

    let parent_refs = if let Some(variant_ref) = variant_ref {
        if refresh {
            let commit = variant_ref.peel_to_commit()?;
            vec![commit]
        } else {
            anyhow::bail!("Variant already exists. Use --refresh to update it.");
        }
    } else {
        vec![]
    };
    let parent_refs: Vec<&Commit> = parent_refs.iter().collect();

    let target_features: HashSet<String> = features.iter().cloned().collect();
    let sig = repo.signature()?;

    let head = repo.head()?;
    let head_commit = head.peel_to_commit()?;
    let tree = head.peel_to_tree()?;

    let variant_tree_oid = build_variant_tree(repo, &tree, Path::new(""), &target_features)?;
    let variant_tree = repo.find_tree(variant_tree_oid)?;

    repo.commit(
        Some(&ref_name),
        &sig,
        &sig,
        &format!("variant derivation with features {:?}", features),
        &variant_tree,
        &parent_refs,
    )?;

    // Store info about the base state
    let mut meta_store = read_variant_meta(repo).unwrap_or_default();
    let meta = VariantMeta {
        commit: head_commit.id().to_string(),
        tree: tree.id().to_string(),
        features: features.clone(),
        created_at: Utc::now().to_rfc3339(),
    };
    meta_store.variants.insert(name.to_string(), meta);
    write_variant_meta(repo, &meta_store)?;

    // Switch to the derived variant branch
    repo.set_head(&ref_name)?;
    repo.checkout_head(Some(git2::build::CheckoutBuilder::new().force()))?;
    Ok(())
}

/// Resolves the instance `name` against the project's `model.cfr` feature model,
/// returning the sorted list of included leaf features.
fn derive_features(repo: &Repository, name: &str) -> Result<Vec<String>> {
    let base_path = repo
        .path()
        .parent()
        .context("Repository has no parent directory")?;
    let model_path = base_path.join("model.cfr");
    let source = std::fs::read_to_string(&model_path)
        .with_context(|| format!("Failed to read model file {}", model_path.display()))?;

    let decls = parse_clafer_module(&source);
    let config = Evaluator::new(decls).resolve_instance(name)?;

    let mut features: Vec<String> = config.included.into_iter().collect();
    features.sort();
    Ok(features)
}

fn build_variant_tree(
    repo: &Repository,
    tree: &Tree,
    base_path: &Path,
    target_features: &HashSet<String>,
) -> Result<Oid> {
    let mut builder = repo.treebuilder(None)?;
    for entry in tree.iter() {
        let name = entry
            .name()
            .ok_or_else(|| anyhow!("tree entry without valid UTF-8 name"))?;
        let full_path = base_path.join(name);

        match entry.kind() {
            Some(ObjectType::Blob) => {
                let content = process_file(repo, &full_path, target_features)
                    .with_context(|| format!("Failed to process file {}", full_path.display()))?;
                let oid = repo.blob(content.as_bytes())?;
                builder.insert(name, oid, entry.filemode())?;
            }
            Some(ObjectType::Tree) => {
                let subtree = repo.find_tree(entry.id())?;
                let subtree_oid = build_variant_tree(repo, &subtree, &full_path, target_features)
                    .with_context(|| {
                    format!("Failed to process directory: {}", full_path.display())
                })?;
                builder.insert(name, subtree_oid, entry.filemode())?;
            }
            _ => {}
        }
    }

    Ok(builder.write()?)
}

fn process_file(
    repo: &Repository,
    name: &PathBuf,
    target_features: &HashSet<String>,
) -> Result<String> {
    let file = File::open(name)?;
    let reader = BufReader::new(file);
    let lines: Vec<String> = reader.lines().collect::<Result<_, _>>()?;
    let mut output: Vec<String> = vec![];

    let mut hidden_start: Option<usize> = None;
    let mut current_hidden_feature: Option<String> = None;
    let mut commit_cache: HashMap<Oid, Option<String>> = HashMap::new();

    let mut blame_opts = BlameOptions::new();
    let blame = repo.blame_file(Path::new(name), Some(&mut blame_opts))?;

    for (i, line) in lines.iter().enumerate() {
        let line_no = i + 1;
        let hunk = blame.get_line(line_no).context("Cant get line info")?;
        let oid = hunk.final_commit_id();

        let line_feature = commit_cache.entry(oid).or_insert_with(|| {
            let commit = repo.find_commit(oid).ok()?;
            let summary = commit.message()?;
            extract_feature_meta(summary).map(|s| s.to_string())
        });

        let is_visible = match line_feature {
            Some(f) => target_features.contains(f),
            None => true,
        };

        if is_visible {
            // Close existing hidden block if exists
            if let (Some(start), Some(feature)) =
                (hidden_start.take(), current_hidden_feature.take())
            {
                output.push(format!(
                    "# morph:{}-{} hidden feature '{}'",
                    start,
                    line_no - 1,
                    feature
                ));
            }
            output.push(line.clone());
        } else {
            if hidden_start.is_none() {
                // New hidden block starts
                hidden_start = Some(line_no);
                current_hidden_feature = line_feature.clone();
            } else if current_hidden_feature.as_ref() != line_feature.as_ref() {
                // Feature changed while still in a hidden state: Close old, start new
                if let Some(feature) = current_hidden_feature.take() {
                    output.push(format!(
                        "# morph:{}-{} hidden feature '{}'",
                        hidden_start.unwrap(),
                        line_no - 1,
                        feature
                    ));
                }
                hidden_start = Some(line_no);
                current_hidden_feature = line_feature.clone();
            }
        }
    }

    if let (Some(start), Some(feature)) = (hidden_start, current_hidden_feature) {
        output.push(format!(
            "# morph:{}-{} hidden feature '{}'",
            start,
            lines.len(),
            feature
        ));
    }

    Ok(output.join("\n"))
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
        let msg = "chore: init\n\nFEATURE: core";
        assert_eq!(extract_feature_meta(msg), Some("core"));
    }

    #[test]
    fn extracts_feature_with_other_metadata() {
        let msg = "\
chore: initialize fog support in repo

CHANGE_ID: de9378ec963973b367aa0ad706fa006af3ce65da
FEATURE: core";
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
