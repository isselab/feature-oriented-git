
# Feature-oriented Git

This tool provides advanced Git feature management, allowing you to associate feature information with commits and files.

## Installation + Preparation

1. Install the tool using pip:
    1. Download the latest release file (currently, the project is not stored in the PIP Index)
    1. Install the tool using pip
        ```bash
        pip install <DownloadPath>/git-tool-<version>-py3-none-any.whl
        ```
1. In each Git repository where you want to track feature information, add the hooks provided by this project. This step is essential to ensure the internal state remains up-to-date. ***Each hook can only exist once. If you already have hooks, you need to manually copy the file contents instead***

    1. **Find the tool's installation path**:
        ```bash
        pip show git-feature-tool
        ```
        Output example:
        ```
        Location: /path/to/your/python/site-packages/git_tool
        ```
    1. **Set the hooks path**:
        ```bash
        git config core.hooksPath /path/to/your/python/site-packages/git_tool/hooks
        ```
        This sets up Git to use the hooks from the specified directory.

## Commands Overview

### `git feature status`

Displays the current feature status, including staged, unstaged, and untracked files with their associated features.

**Usage**:
```bash
git feature status
```
### `git feature add`
This command helps to associate feature information with a commit that does not yet exist. You can either add the information while adding the files or add features to the staging area.
If you prefer to keep your workflows as usual and add feature information solely to commits that you already created, you don't need the git hooks and can jump to `git feature-commit`.

#### `git feature add`

Associates specified features with staged files. You can stage specific files or all tracked changes.

**Options**:
- `--all`, `-a`: Stages all tracked changes.
- `--files`, `-f`: Specifies a list of files to stage and associate with features.

**Usage**:
```bash
git feature add --all <feature-names>
git feature add --files <file>... <feature-names>
```

#### `git feature add-from-staged`

Uses staged files to associate them with feature information.

**Usage**:
```bash
git feature add-from-staged
```


### `git feature commit`
Assign features to a commit retroactively. To find all commits that have not yet features assigned, see ---
**Usage**:
```bash
git feature commit <commit_id> <features>
```

### `git feature blame`

Displays the feature associations for each line of a specified file, similar to `git blame`.

**Usage**:
```bash
git feature blame <file>
```

### `git feature info`

Displays detailed information about a feature, including associated commits, files, authors, and branches.

**Options**:
- `--authors`: Lists the authors who contributed to the feature.
- `--files`: Lists the files associated with the feature.
- `--branches`: Lists the branches where the feature is present.
- `--updatable`: Check if the feature has updates available on other branches and list the update options.
- `--branch <branch_name>`: Specify a branch for checking updates (used with `--updatable`).

**Usage**:
```bash
git feature info <feature>
git feature info <feature> --authors --files --branches
```

### `git feature commits`

Lists all commits associated with a feature or shows commits that are missing feature associations.

**Commands**:
- `missing`: Lists commits that do not have any associated feature.
- `list`: List commits that are associated to features.

**Usage**:
```bash
git feature commits list
git feature commits missing
```

---

## Example Usage

1. **Check Feature Status**:
   ```bash
   git feature status
   ```

2. **Add Features to All Files**:
   ```bash
   git feature add --all "new-feature"
   ```

3. **Add Features to Specific Files**:
   ```bash
   git feature add --files src/main.py "feature-x"
   ```

4. **Use Staged Files for Feature Information**:
   ```bash
   git feature add-from-staged
   ```

5. **Show Feature Associations for a File**:
   ```bash
   git feature blame src/main.py
   ```

6. **Display Feature Information**:
   ```bash
   git feature info feature-x --authors --files --branches
   ```

7. **List All Commits With and Without Features**:
   ```bash
   git feature commits list
   git feature commits missing
   ```

---

For further details or to explore more usage options, refer to the [Typer Documentation](https://typer.tiangolo.com/tutorial/).



## Development
1. Create a virtual environment and install both requirement-files.

### Rust Components

To build and run the rust components, use standard Cargo commands from the project root:

```bash
# Build the project
cargo build

# Run the project
cargo run
```

The binary will be compiled into `target/debug/git-vms`.

**Symlinking Binaries**

For rapid development, you can symlink the compiled binaries to a location in your `$PATH` so you can run them like any other git command:

```bash
ln -s $(pwd)/target/debug/git-vms /path/to/your/bin/git-vms
```

After that, you can run the binary directly:

```bash
git vms --version
```
