use anyhow::{Context, Result};
use git2::{BranchType, Commit, Repository, Sort};
use regex::Regex;

use std::collections::HashSet;

pub fn diff(repo: &Repository, target: &str, reverse: bool) -> Result<()> {
    let current_ref = repo.head()?;
    let target_ref = repo
        .find_branch(target, BranchType::Local)
        .context("Specified target branch does not exist")?
        .into_reference();

    let (current_ref, target_ref) = if reverse {
        (target_ref, current_ref)
    } else {
        (current_ref, target_ref)
    };

    let current_ref_name = current_ref
        .name()
        .context("Reference has no valid UTF-8 name")?;
    let target_ref_name = target_ref
        .name()
        .context("Reference has no valid UTF-8 name")?;

    let exclude_set: HashSet<_> = extract_change_ids(repo, current_ref_name)?;

    let missing_commits = filter_missing_commits(repo, target_ref_name, &exclude_set)?;

    for commit in &missing_commits {
        let summary = commit.summary().context("Error fetching commit summary")?;
        println!("{:.7}\t{}", commit.id(), summary);
    }
    Ok(())
}

fn extract_change_ids(repo: &Repository, reference: &str) -> Result<HashSet<String>> {
    let mut ids: HashSet<String> = HashSet::new();

    let mut revwalk = repo.revwalk()?;
    revwalk.push_ref(reference)?;
    revwalk.set_sorting(Sort::TOPOLOGICAL | Sort::TIME)?;

    for oid in revwalk {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;
        let message = commit
            .message()
            .context("Commit message is not valid UTF-8")?;
        let change_id = extract_change_id(message)
            .context("Failed to extract change-id from commit message")?;

        ids.insert(change_id);
    }
    Ok(ids)
}

fn filter_missing_commits<'repo>(
    repo: &'repo Repository,
    ref_name: &str,
    exclude_set: &HashSet<String>,
) -> Result<Vec<Commit<'repo>>> {
    let mut missing: Vec<Commit> = Vec::new();
    let mut revwalk = repo.revwalk()?;
    revwalk.push_ref(ref_name)?;
    revwalk.set_sorting(Sort::TOPOLOGICAL | Sort::TIME)?;

    for oid in revwalk {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;
        let message = commit.message().context("Commit has no message!")?;
        let change_id = extract_change_id(message)
            .context("Failed to extract change-id from commit message")?;
        if !exclude_set.contains(&change_id) {
            missing.push(commit);
        }
    }
    Ok(missing)
}

// TODO: building each time can be expensive. Look for an alternative
fn extract_change_id(msg: &str) -> Option<String> {
    let re = Regex::new(r"CHANGE_ID:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b)").unwrap();
    re.captures(msg)
        .and_then(|caps| caps.get(1).map(|m| m.as_str().to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_valid_change_id() {
        let msg = r#"
feat(api)!: send an email to the customer when a product is shipped

CHANGE_ID: fec54ceb-74fe-4c6e-b467-cee066ffa268
"#;
        let result = extract_change_id(msg);
        assert_eq!(
            result,
            Some("fec54ceb-74fe-4c6e-b467-cee066ffa268".to_string())
        );
    }

    #[test]
    fn returns_none_when_no_change_id_present() {
        let msg = r#"
feat(api)!: send an email to the customer when a product is shipped
"#;

        let result = extract_change_id(msg);
        assert_eq!(result, None);
    }

    #[test]
    fn returns_none_for_invalid_uuid_format() {
        let msg = r#"
feat(api)!: send an email to the customer when a product is shipped

CHANGE_ID: fec54ceb-74fe-4c6e-b467-cee066ffa268abc
"#;

        let result = extract_change_id(msg);
        assert_eq!(result, None);
    }
}
