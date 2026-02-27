use anyhow::{Context, Result};
use git2::{Diff, Index, IndexEntry, IndexTime, Oid, Repository, Signature, Sort, Tree};
use regex::Regex;
use std::path::{Path, PathBuf};

use std::collections::{HashMap, HashSet};

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

fn extract_hunks(diff: Diff) -> HashMap<PathBuf, Vec<(u32, Vec<u8>)>> {
    let mut additions: HashMap<PathBuf, Vec<(u32, Vec<u8>)>> = HashMap::new();
    diff.foreach(
        &mut |_, _| true,
        None,
        None,
        Some(&mut |delta, _hunk, line| {
            if line.origin() != '+' {
                return true;
            }
            let path = delta
                .new_file()
                .path()
                .or_else(|| delta.old_file().path())
                .unwrap();

            let new_lineno = line.new_lineno().unwrap();
            additions
                .entry(path.to_path_buf())
                .or_default()
                .push((new_lineno, line.content().to_vec()));
            true
        }),
    )
    .unwrap();
    additions
}

fn get_file_bytes_from_tree(repo: &Repository, tree: &Tree, path: &Path) -> Result<Vec<u8>> {
    match tree.get_path(path) {
        Ok(entry) => {
            let blob = repo.find_blob(entry.id())?;
            Ok(blob.content().to_vec())
        }
        Err(_) => Ok(Vec::new()),
    }
}

fn split_lines_including_newline(bytes: &[u8]) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let mut start = 0usize;

    for (i, &b) in bytes.iter().enumerate() {
        if b == b'\n' {
            out.push(bytes[start..=i].to_vec());
            start = i + 1;
        }
    }

    if start < bytes.len() {
        out.push(bytes[start..].to_vec());
    }
    out
}

fn join_lines(lines: &[Vec<u8>]) -> Vec<u8> {
    let mut out = Vec::new();
    for line in lines {
        out.extend_from_slice(line);
    }
    out
}

fn ensure_length(lines: &mut Vec<Vec<u8>>, len: usize) {
    while lines.len() < len {
        lines.push(b"\n".to_vec());
    }
}

fn apply_additions(base: Vec<u8>, mut additions: Vec<(u32, Vec<u8>)>) -> Vec<u8> {
    additions.sort_by_key(|(ln, _)| *ln);
    let mut lines = split_lines_including_newline(&base);

    for (new_lineno, content) in additions {
        let idx = (new_lineno as usize).saturating_sub(1);

        ensure_length(&mut lines, idx);
        if idx >= lines.len() {
            lines.push(content);
        } else {
            lines.insert(idx, content);
        }
    }

    join_lines(&lines)
}

pub fn derive(repo: &Repository, name: &str, features: &[String]) -> Result<()> {
    println!("Deriving variant '{}' with features: {:?}", name, features);
    // create a new orphan branch
    let ref_name = format!("refs/heads/variant/{name}");
    let sig = Signature::now("user", "user@example.com")?;
    let mut variant_head_oid = create_variant_initial_commit(repo, &ref_name, &sig)?;

    let target_features: HashSet<String> = features.iter().cloned().collect();

    // walk the commit graph
    let mut revwalk = repo.revwalk()?;
    revwalk.push_head()?;
    revwalk.set_sorting(Sort::TOPOLOGICAL | Sort::TIME | Sort::REVERSE)?;

    for oid in revwalk {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;

        let summary = commit.summary().context("Error extracting summary")?;
        if let Some(feature) = extract_scope(summary)
            && !target_features.contains(feature)
        {
            continue;
        }

        if commit.parent_count() == 0 {
            println!("Commit '{}'has no parent. Skipping.", commit.id());
            continue;
        }
        let parent = commit.parent(0)?;

        let commit_tree = commit.tree()?;
        let parent_tree = parent.tree()?;

        let diff = repo.diff_tree_to_tree(Some(&parent_tree), Some(&commit_tree), None)?;
        let additions = extract_hunks(diff);

        // write changes to disk without touching the worktree
        if !additions.is_empty() {
            let variant_parent = repo.find_commit(variant_head_oid)?;
            let variant_tree = variant_parent.tree()?;

            let mut index = Index::new()?;
            index.read_tree(&variant_tree)?;

            for (path, contents) in additions {
                let base = get_file_bytes_from_tree(repo, &variant_tree, &path)?;
                let merged = apply_additions(base, contents);

                let blob_oid = repo.blob(&merged)?;
                let path_string = path.to_string_lossy().replace('\\', "/");
                let entry = IndexEntry {
                    ctime: IndexTime::new(0, 0),
                    mtime: IndexTime::new(0, 0),
                    dev: 0,
                    ino: 0,
                    mode: 0o100644,
                    uid: 0,
                    gid: 0,
                    file_size: merged.len() as u32,
                    id: blob_oid,
                    flags: 0,
                    flags_extended: 0,
                    path: path_string.into_bytes(),
                };
                index.add(&entry)?;
            }
            let new_tree_oid = index.write_tree_to(repo)?;
            let new_tree = repo.find_tree(new_tree_oid)?;

            let commit_msg = commit.message().unwrap();
            variant_head_oid = repo.commit(
                Some(&ref_name),
                &sig,
                &sig,
                commit_msg,
                &new_tree,
                &[&variant_parent],
            )?;
        }
    }

    let var_ref_name = format!("refs/variants/{name}");
    let target_ref = repo.find_reference(&ref_name)?;
    let var_ref_target = target_ref.name().context("Branch has invalid UTF-8 name")?;

    repo.reference_symbolic(
        &var_ref_name,
        var_ref_target,
        false,
        "initialized new variant",
    )
    .context("Failed to create symbolic ref to variant")?;
    Ok(())
}

// TODO: building each time can be expensive. Look for an alternative
fn extract_scope(commit: &str) -> Option<&str> {
    let re = Regex::new(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:").unwrap();
    re.captures(commit)
        .and_then(|caps| caps.name("scope").map(|m| m.as_str()))
}

#[cfg(test)]
mod tests {
    use super::extract_scope;

    #[test]
    fn extracts_scope_when_present() {
        assert_eq!(extract_scope("feat(auth): add login"), Some("auth"));
    }

    #[test]
    fn extracts_scope_with_breaking_change() {
        assert_eq!(
            extract_scope("feat(api)!: change response format"),
            Some("api")
        );
    }

    #[test]
    fn returns_none_when_no_scope() {
        assert_eq!(extract_scope("fix: missing semicolon"), None);
    }

    #[test]
    fn does_not_match_invalid_format() {
        assert_eq!(extract_scope("not a conventional commit"), None);
    }
}
