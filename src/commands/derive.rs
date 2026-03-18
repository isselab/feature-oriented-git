use anyhow::{Context, Result};
use git2::{
    BlameOptions, Diff, Index, IndexEntry, IndexTime, Oid, Repository, Signature, Sort, Status,
    Tree, TreeWalkResult,
};
use regex::Regex;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

use std::collections::{HashMap, HashSet};

enum LineEdit {
    Add { line: u32, content: Vec<u8> },
    Delete { line: u32 },
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

fn extract_line_edits(diff: Diff) -> HashMap<PathBuf, Vec<LineEdit>> {
    let mut edits: HashMap<PathBuf, Vec<LineEdit>> = HashMap::new();
    diff.foreach(
        &mut |_, _| true,
        None,
        None,
        Some(&mut |delta, _hunk, line| {
            let path = delta
                .new_file()
                .path()
                .or_else(|| delta.old_file().path())
                .unwrap()
                .to_path_buf();

            match line.origin() {
                '+' => {
                    if let Some(new_lineno) = line.new_lineno() {
                        edits.entry(path).or_default().push(LineEdit::Add {
                            line: new_lineno,
                            content: line.content().to_vec(),
                        })
                    }
                }
                '-' => {
                    if let Some(old_lineno) = line.old_lineno() {
                        edits
                            .entry(path)
                            .or_default()
                            .push(LineEdit::Delete { line: old_lineno })
                    }
                }
                _ => {}
            }
            true
        }),
    )
    .unwrap();
    edits
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

fn apply_changes(base: Vec<u8>, edits: Vec<LineEdit>) -> Vec<u8> {
    let mut deletes = Vec::new();
    let mut adds = Vec::new();

    for edit in edits {
        match edit {
            LineEdit::Delete { .. } => deletes.push(edit),
            LineEdit::Add { .. } => adds.push(edit),
        }
    }
    deletes.sort_by_key(|edit| match edit {
        LineEdit::Delete { line } => *line,
        _ => unreachable!(),
    });
    adds.sort_by_key(|edit| match edit {
        LineEdit::Add { line, .. } => *line,
        _ => unreachable!(),
    });
    deletes.reverse();

    let mut lines = split_lines_including_newline(&base);

    for edit in deletes {
        if let LineEdit::Delete { line } = edit {
            let idx = (line as usize).saturating_sub(1);
            if idx < lines.len() {
                lines.remove(idx);
            }
        }
    }

    for edit in adds {
        if let LineEdit::Add { line, content } = edit {
            let idx = (line as usize).saturating_sub(1);
            ensure_length(&mut lines, idx);
            if idx >= lines.len() {
                lines.push(content);
            } else {
                lines.insert(idx, content);
            }
        }
    }

    join_lines(&lines)
}

pub fn derive(repo: &Repository, name: &str, features: &[String]) -> Result<()> {
    println!("Deriving variant '{}' with features: {:?}", name, features);

    let config = repo.config()?.snapshot()?;
    let user_name = config.get_str("user.name")?;
    let user_email = config.get_str("user.email")?;
    let sig = Signature::now(user_name, user_email)?;

    // create a new orphan branch
    let ref_name = format!("refs/heads/variant/{name}");
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
        let additions = extract_line_edits(diff);

        // write changes to disk without touching the worktree
        if !additions.is_empty() {
            let variant_parent = repo.find_commit(variant_head_oid)?;
            let variant_tree = variant_parent.tree()?;

            let mut index = Index::new()?;
            index.read_tree(&variant_tree)?;

            for (path, contents) in additions {
                let base = get_file_bytes_from_tree(repo, &variant_tree, &path)?;
                let merged = apply_changes(base, contents);

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
            let commit_author = commit.author();
            variant_head_oid = repo.commit(
                Some(&ref_name),
                &commit_author,
                &commit_author,
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

pub fn derive_no_history(repo: &Repository, name: &str, features: &[String]) -> Result<()> {
    let statuses = repo.statuses(None)?;
    for entry in statuses.iter() {
        let s = entry.status();
        if s != Status::CURRENT {
            println!("Repository is not clean!");
            return Ok(());
        }
    }

    let ref_name = format!("refs/heads/variant/{name}");
    let sig = repo.signature()?;
    let variant_head_oid = create_variant_initial_commit(repo, &ref_name, &sig)?;

    let target_features: HashSet<String> = features.iter().cloned().collect();
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
        "derive no history",
        &variant_tree,
        &[&variant_parent],
    )?;
    Ok(())
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
            let summary = commit.summary().unwrap();
            extract_scope(summary).is_some_and(|feature| target_features.contains(feature))
        });

        if !*contains_feature {
            *line = String::new();
        }
    }

    // lines.retain(|line| !line.is_empty());
    Ok(lines.join("\n"))
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
