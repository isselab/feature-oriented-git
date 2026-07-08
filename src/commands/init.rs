use std::fs;
use std::io::Write;

use anyhow::{Context, Result};
use git2::Repository;

const DEFAULT_MODEL: &str = r#"// git-varcs feature model
// Describe your feature model as an abstract clafer, then declare each
// variant as a concrete instance that selects the features it needs.
//
// abstract Product {
//     xor Storage {
//         SQLite
//         Postgres
//     }
//     Scanner ?
// }
//
// MyVariant : Product {
//     [ SQLite ]
//     [ Scanner ]
// }
"#;

pub fn run(repo: &Repository) -> Result<()> {
    let base_path = repo
        .path()
        .parent()
        .context("Repository has no parent directory")?;
    let model_path = base_path.join("model.cfr");
    let meta_path = base_path.join(".git/varcs");

    fs::create_dir(meta_path)?;

    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&model_path)
        .with_context(|| format!("Failed to create model file at path: {:?}", model_path))?;

    file.write(DEFAULT_MODEL.as_bytes())
        .with_context(|| format!("Failed to write default model to: {:?}", model_path))?;

    println!("Initialized feature model at {}", model_path.display());
    Ok(())
}
