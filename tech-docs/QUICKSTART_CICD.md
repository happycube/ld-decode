# CI/CD Quick Start

A short orientation to what CI does with your changes. Full detail is in
[CICD.md](CICD.md); the workflows in [`.github/workflows/`](../.github/workflows/)
are the source of truth.

## What runs when

### On every pull request

**Build and Test** ([`build-and-test.yml`](../.github/workflows/build-and-test.yml))
runs, as three stages:

1. **Unit Tests** — the hermetic pytest lane, ~minutes. Checked out without
   submodules: if a test needs real capture data it fails here, which is the point.
2. **Functional Tests** and **VITS Conformance**, side by side — the two CTest
   lanes (`ctest -LE vits` and `ctest -L vits`), each with its own job so a
   radius-specific fault names itself. These need the `testdata/` submodule, which
   CI checks out recursively.
3. **Packaging** — AppImage, macOS DMG and Windows ZIP builds, each gated on both
   test lanes passing.

### On push to main

The same pipeline, uncancellable, plus **deploy-docs**, which publishes the MkDocs
site to GitHub Pages.

### On a version tag

Pushing a tag `v*` runs the full pipeline, and on success the three packaging jobs
attach their artefacts to the GitHub Release for that tag. That is the whole
release process — there is no separate release workflow.

## Reproducing the lanes locally

CI runs exactly what the developer workflow runs, under Nix:

```bash
nix develop

python -m pytest -q tests/unit                     # the unit lane
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
ctest --test-dir build -L functional --output-on-failure
ctest --test-dir build -L vits --output-on-failure
```

The functional lanes need the `testdata/` submodule checked out.

## Creating a release

```bash
# 1. Version metadata lives in pyproject.toml.
#    Do not hand-edit lddecode/version - it is generated from git.
# 2. Tag and push:
git tag -a v7.0.0 -m "Release version 7.0.0"
git push origin v7.0.0
```

## When a build fails

- Read the failing job's log in the Actions tab; each lane logs separately.
- A red **VITS Conformance** job still writes a step summary with the measured
  values and the bands they missed — read that first.
- To debug a functional failure without pushing, dispatch the manual
  **Functional Tests** workflow ([`functional-tests.yml`](../.github/workflows/functional-tests.yml))
  on your branch.
- Reproduce locally with the commands above before opening a PR, especially for
  decode-behaviour changes, which are also covered by the serial/threaded
  bit-identity checks (`ctest -R "parallel"`).

## Additional Resources

- [CICD.md](CICD.md) — the full CI/CD reference
- [BUILD.md](../BUILD.md) — build instructions
- [TESTING.md](../TESTING.md) — test strategy and the unit/functional split
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contribution guidelines
