"""
Build hooks for setuptools to generate version information before building.
"""

import os
import subprocess
import sys


def get_git_branch():
    """Get the current git branch name."""
    try:
        sp = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True,
            cwd=os.path.dirname(__file__)
        )
        if sp.returncode == 0:
            branch = sp.stdout.strip()
            # If in detached HEAD state (from a tag), use "release"
            if branch == "HEAD":
                return "release"
            return branch
    except Exception:
        pass
    return "release"


def get_git_commit():
    """Get the current git commit hash or version tag."""
    try:
        # First, try to get the version tag for the current commit
        sp = subprocess.run(
            "git describe --tags --exact-match",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True,
            cwd=os.path.dirname(__file__)
        )
        if sp.returncode == 0:
            tag = sp.stdout.strip()
            # Remove 'v' prefix if present
            if tag.startswith('v'):
                tag = tag[1:]
            return tag

        # If not on a tag, use git describe with commits since tag
        sp = subprocess.run(
            "git describe --tags --always",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True,
            cwd=os.path.dirname(__file__)
        )
        if sp.returncode == 0:
            commit = sp.stdout.strip()
            # Remove 'v' prefix if present
            if commit.startswith('v'):
                commit = commit[1:]
            return commit

        # Fallback to short commit hash
        sp = subprocess.run(
            "git rev-parse --short HEAD",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True,
            cwd=os.path.dirname(__file__)
        )
        if sp.returncode == 0:
            return sp.stdout.strip()
    except Exception:
        pass

    return "unknown"


def is_git_dirty():
    """Check if git repository has uncommitted changes."""
    try:
        sp = subprocess.run(
            "git status --porcelain",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True,
            cwd=os.path.dirname(__file__)
        )
        if sp.returncode == 0:
            output = sp.stdout.strip()
            return len(output) > 0
    except Exception:
        pass
    return False


def hook(config):
    """
    Setuptools build hook: generate version file before building.
    
    This is called by setuptools during the build process.
    """
    branch = get_git_branch()
    commit = get_git_commit()
    dirty = is_git_dirty()

    # Generate version string in format: branch:commit[:dirty]
    version = f"{branch}:{commit}"
    if dirty:
        version += ":dirty"

    # Write to version file
    version_file = os.path.join(os.path.dirname(__file__), "lddecode", "version")
    with open(version_file, 'w') as f:
        f.write(version + "\n")

    print(f"[build hook] Generated version: {version}")
