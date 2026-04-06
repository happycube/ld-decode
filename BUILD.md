# Building ld-decode (Nix)

This project is built with [Nix](https://nixos.org/). The flake provides a reproducible build and generates the version file automatically.

## Requirements

- [Nix](https://nixos.org/) — a purely functional package manager that provides reproducible, declarative builds. Flakes must be enabled.

## Build

- Build the default package:
  - `nix build`

The build produces `./result` with the installed package and CLI tools.

## Run

- Run the main tool:
  - `nix run`
- Or run a specific tool:
  - `nix run .#ld-decode`
  - `nix run .#ld-ldf-reader-py`

## Development shell

- Enter a dev shell with dependencies:
  - `nix develop`

## Versioning

The flake generates a PEP 440 compliant version string and writes it to `lddecode/version` during the build. The CLI `--version` output comes from that file and includes git commit and dirty status when available.

## Documentation

The project documentation lives in `docs/` and is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/). All required dependencies (`mkdocs`, `mkdocs-material`, `mkdocs-awesome-nav`) are provided by the Nix dev shell.

- Enter the dev shell first (if not already inside one):
  - `nix develop`

- Start a live-reload preview server at `http://127.0.0.1:8000/`:
  - `mkdocs serve`

- Build a static site into `site/`:
  - `mkdocs build`

- Build the docs as a Nix package (output in `./result/`):
  - `nix build .#docs`
