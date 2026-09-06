# CI/CD and Release Process

This repository uses GitHub Actions for continuous integration and release packaging.
The authoritative description of what CI does is the workflows themselves, in
[`.github/workflows/`](../.github/workflows/); this document summarises them. If the two
disagree, the workflows win.

All test lanes run on `ubuntu-latest` under [Nix](../flake.nix), on the Python version
pinned there (currently 3.12). There is no per-version test matrix.

## Workflows

| Workflow | Purpose | Runs on |
|----------|---------|---------|
| [`build-and-test.yml`](../.github/workflows/build-and-test.yml) | The primary gate: tests, then packaging | Push (any branch), tags `v*`, PRs, releases |
| [`functional-tests.yml`](../.github/workflows/functional-tests.yml) | The full functional lane, standalone | Manual dispatch only |
| [`appimage.yml`](../.github/workflows/appimage.yml) | Linux AppImage | Called by build-and-test |
| [`macos-dmg.yml`](../.github/workflows/macos-dmg.yml) | macOS DMG | Called by build-and-test |
| [`windows-zip.yml`](../.github/workflows/windows-zip.yml) | Windows portable ZIP | Called by build-and-test |
| [`deploy-docs.yml`](../.github/workflows/deploy-docs.yml) | MkDocs site to GitHub Pages | Push to main, PRs (build only), manual |

### Build and Test

The primary gate. A superseded run is cancelled (the suite takes about two hours
end to end), except on `main` and on tags, where the run produces release artefacts.

Jobs, in dependency order:

1. **unit-tests** — the fast gate. Checks out *without* submodules, which keeps the
   hermeticity of the unit lane honest: a suite that reads capture data fails here
   instead of passing quietly on a populated checkout. Runs
   `pytest -q tests/unit --strict-markers` with coverage; coverage is reported, not
   enforced. Timeout: 20 min.
2. **functional-tests** — everything except the VITS radius sweep. Checks out
   submodules recursively, configures CMake, runs `ctest -LE vits`. Needs the
   `testdata/` submodule. Timeout: 120 min.
3. **vits-conformance** — the VITS radius sweep (`ctest -L vits`), as its own job
   so its output is a step summary a developer reads rather than a line in a
   two-hour log. Uploads the `*.conformance.json` reports as an artefact whether
   it passed or failed. Timeout: 90 min.
4. **build-appimage / build-macos-dmg / build-windows-zip** — the three packaging
   jobs (below), each gated on both test lanes passing.

### Functional Tests (manual)

[`functional-tests.yml`](../.github/workflows/functional-tests.yml) runs the complete
`ctest` suite (functional *and* VITS, no label exclusion) on manual dispatch from the
Actions tab, for debugging a failure without pushing.

### deploy-docs

Builds the MkDocs Material site (`mkdocs build --strict`) and deploys it to GitHub
Pages on push to `main`. On pull requests it builds without deploying, so a broken
docs build fails the PR.

## Packaging

Each packaging job builds its platform's artefact, smoke-tests it, uploads it as a
workflow artefact (30-day retention), and attaches it to the GitHub Release when the
run was triggered by a `v*` tag.

- **Linux — AppImage** (`appimage.yml`): built around a relocatable
  python-build-standalone CPython 3.12, with self-locating wrappers for
  `ld-decode`, `ld-cut`, `ld-compress`, `ld-ldf-reader-py` and `ld-lds-converter-py`,
  plus a statically-linked flac 1.5.0 (the one external program `ld-compress` shells
  out to). The job verifies the bundle runs from a relocated copy with a scrubbed
  environment and that an `ld-compress` round trip is lossless before packaging.
- **macOS — DMG** (`macos-dmg.yml`): PyInstaller onefile binaries inside
  `LD-Decode.app`, ad-hoc code signed, with flac built from source and linked
  statically. Smoke-tested before packaging.
- **Windows — portable ZIP** (`windows-zip.yml`): no installer; a ZIP containing
  the full CPython 3.12 runtime, the `lddecode` package, `.bat` wrappers in `bin\`,
  and the official Xiph flac 1.5.0 Win64 build. Smoke-tested, including the
  `ld-compress` round trip, before packaging.

## Creating a Release

1. Make sure the version in [`pyproject.toml`](../pyproject.toml) is current.
   `lddecode/version` is **not** hand-edited: it is generated from git by CMake
   configure and by [`scripts/generate_version.py`](../scripts/generate_version.py),
   and the packaging jobs regenerate it during their build.
2. Tag and push:

   ```bash
   git tag -a v7.0.0 -m "Release version 7.0.0"
   git push origin v7.0.0
   ```

The tag runs the full Build and Test pipeline; when it passes, the three packaging
jobs attach their artefacts to the GitHub Release for that tag. There is no separate
release workflow and no manual dispatch path that publishes.

## Reproducing CI Locally

The lanes are the same ones a developer runs (see [BUILD.md](../BUILD.md) and
[TESTING.md](../TESTING.md)):

```bash
nix develop

# The unit lane
python -m pytest -q tests/unit

# The functional and VITS lanes (needs the testdata/ submodule)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
ctest --test-dir build -L unit --output-on-failure
ctest --test-dir build -L functional --output-on-failure
ctest --test-dir build -L vits --output-on-failure
```

## Troubleshooting

- A red **Functional Tests** or **VITS Conformance** job on a PR usually means the
  `testdata/` submodule is stale relative to the code; check what the failing test
  reads.
- The **VITS Conformance** step summary shows the measured values and the bands
  they missed even when the job is red; read it before downloading the report
  artefact.
- To re-run the full suite against a PR branch without pushing, use the manual
  **Functional Tests** dispatch after checking out the branch.

## Additional Resources

- [BUILD.md](../BUILD.md) — build instructions
- [INSTALL.md](../INSTALL.md) — installation instructions
- [TESTING.md](../TESTING.md) — test strategy and the unit/functional split
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contribution guidelines
