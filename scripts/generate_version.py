#!/usr/bin/env python3
"""
Generate version information from git repository.

This script generates version info including branch, commit, and dirty state
that can be embedded in builds. The output format is:
    branch:commit[:dirty]

The base version is read from flake.nix (the single source of truth, as used
by the CMake configure step and the Nix build), falling back to an exact git
tag. This supports all build types: source and GitHub Actions packaging.
"""

import subprocess
import sys
import os
import re


def get_git_branch():
    """Get the current git branch name."""
    try:
        sp = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True
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


def get_base_version():
    """Get the base version from flake.nix, falling back to an exact git tag."""
    # flake.nix lives in the repository root, one level above scripts/
    flake_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flake.nix"
    )
    try:
        with open(flake_path, "r") as f:
            match = re.search(r'version = "([^"]+)"', f.read())
        if match:
            return match.group(1)
    except Exception:
        pass

    try:
        sp = subprocess.run(
            "git describe --tags --exact-match",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True
        )
        if sp.returncode == 0:
            tag = sp.stdout.strip()
            # Remove 'v' prefix if present
            if tag.startswith('v'):
                tag = tag[1:]
            return tag
    except Exception:
        pass

    return "unknown"


def get_git_commit():
    """Get the version: base version plus the short commit hash."""
    base = get_base_version()
    try:
        sp = subprocess.run(
            "git rev-parse --short HEAD",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True
        )
        if sp.returncode == 0:
            return f"{base}+git.{sp.stdout.strip()}"
    except Exception:
        pass
    return base


def is_git_dirty():
    """Check if git repository has uncommitted changes."""
    try:
        sp = subprocess.run(
            "git status --porcelain",
            shell=True,
            capture_output=True,
            timeout=2,
            text=True
        )
        if sp.returncode == 0:
            output = sp.stdout.strip()
            return len(output) > 0
    except Exception:
        pass
    return False


def generate_version(format_string=None):
    """
    Generate version string from git information.

    Args:
        format_string: Optional format override. If None, uses default format.

    Returns:
        Version string in format: branch:commit[:dirty]
    """
    branch = get_git_branch()
    commit = get_git_commit()
    dirty = is_git_dirty()

    if format_string:
        return format_string.format(branch=branch, commit=commit, dirty=dirty)

    # Default format: branch:commit[:dirty]
    version = f"{branch}:{commit}"
    if dirty:
        version += ":dirty"

    return version


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate version information from git repository"
    )
    parser.add_argument(
        "--format",
        "-f",
        help="Format string with {branch}, {commit}, {dirty} placeholders"
    )
    parser.add_argument(
        "--branch",
        action="store_true",
        help="Output only branch name"
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Output only commit hash"
    )
    parser.add_argument(
        "--dirty",
        action="store_true",
        help="Output dirty flag (exit code 0 if dirty, 1 if clean)"
    )

    args = parser.parse_args()

    if args.branch:
        print(get_git_branch())
    elif args.commit:
        print(get_git_commit())
    elif args.dirty:
        sys.exit(0 if is_git_dirty() else 1)
    elif args.format:
        print(generate_version(args.format))
    else:
        print(generate_version())


if __name__ == "__main__":
    main()
