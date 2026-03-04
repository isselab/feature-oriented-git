use anyhow::Result;
use clap::ValueEnum;
use git2::Repository;

#[derive(Clone, ValueEnum)]
pub enum ItemType {
    Variant,
}

pub fn list(repo: &Repository, kind: ItemType) -> Result<()> {
    match kind {
        ItemType::Variant => {
            let variants = repo.references_glob("refs/variants/*")?;
            for variant in variants {
                if let Some(name) = variant?.name() {
                    let short_name = name.strip_prefix("refs/variants/").unwrap_or(name);
                    println!("{}", short_name);
                }
            }
        }
    }
    Ok(())
}
