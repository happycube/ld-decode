# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2024-04-26

### Added

- Implement a workaround for signed 32Bit overflow in tbc.json produced by `ld-analyze` or other ld-decode-tools
- Proper documentation
- Package CHANGELOG.md into zip
- CSVs have time offset columns that help binjr to better parse them

### Fixed

- Fix links in CHANGELOG.md
- Fix handling of EOF in non-seekable streams (don't try to get the stream position at the end)

## [0.1.0] - 2023-10-15

### Added

- Linear projection with skipping of missing fields works for sync linear audio / PCM1802 recordings from clock generator
- Nearest neighbor interpolation of an input to an output stream 
- CSV creation from TBC JSON to view drift and compensation over a tape

[unreleased]: https://gitlab.com/wolfre/vhs-decode-auto-audio-align/-/compare/v1.0.0...main
[1.0.0]: https://gitlab.com/wolfre/vhs-decode-auto-audio-align/-/compare/v0.1.0...v1.0.0
[0.1.0]: https://gitlab.com/wolfre/vhs-decode-auto-audio-align/-/tree/v0.1.0
