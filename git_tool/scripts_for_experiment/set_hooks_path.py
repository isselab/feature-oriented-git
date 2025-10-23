import subprocess
import os
import sys
import git_tool

'''
    This script sets the hooks path for git.
    It has been added to the pyproject.toml file as "feature-init-hooks"
    Originally, the user had to set the hooks path manually, but not anymore.
'''

def main():
    try:
        # Step 1: Get the path to the installed git_tool package
        package_path = os.path.abspath(git_tool.__file__)
        print(f"Located git_tool at: {package_path}")

        # Step 2: Strip __init__.py and append 'hook'
        base_path = os.path.dirname(package_path)
        hook_path = os.path.join(base_path, "hooks")
        print(f"Using hooks directory: {hook_path}")

        # Step 3: Set git hooksPath
        subprocess.run(["git", "config", "core.hooksPath", hook_path], check=True)
        print("Git hooks path set successfully.")

        # Step 4: Check the current hooks path
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            check=True,
            stdout=subprocess.PIPE,
            text=True
        )
        current_hook_path = result.stdout.strip()
        print(f"Git is now using hooks from: {current_hook_path}")

    except subprocess.CalledProcessError as e:
        print("Git command failed:", e)
        sys.exit(1)
    except Exception as e:
        print("Something went wrong:", e)
        sys.exit(1)