# Building ld-decode (Nix)

This project is built with Nix. The flake provides a reproducible build and generates the version file automatically.

## Requirements

- Nix with flakes enabled

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
