# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-10-10

### Changed

- **Breaking:** the workflow commands are now `biascorrect`, `MPRAGEise`,
  `stripmask`, and `brainmask`.
- The package no longer installs a top-level `scripts` module.

### Added

- First PyPI release, published through trusted publishing.
- Click command-line interface with a `--check` option that verifies the
  selected container and reports the SPM version.
- `spm_biascorrect`, `spm_mprageise`, `spm_stripmask`, and `spm_seg` Python
  functions.
- Docker, Singularity, and Apptainer runtimes for SPM25 Standalone.
- MIT licence, type information (`py.typed`), and continuous integration.

### Notes

- Results have not yet been numerically validated against the historical
  SPM12/MATLAB pipeline.
