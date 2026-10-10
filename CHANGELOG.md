# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [2.5.0] - Unreleased

### Fixed

- SPM now runs with multiple MATLAB threads. The MATLAB Runtime in the SPM
  container defaulted to one thread, so SPM used one core. The default is the
  number of available cores, between 8 and 16.

### Added

- `--engine docker|apptainer` option for choosing the container engine, for
  example on HPC systems.
- `--threads` option and `threads=` keyword to set the number of MATLAB threads.

### Changed

- **Breaking:** the Singularity runtime was removed. Use Apptainer
  (`--engine apptainer`, or `runtime="apptainer"` in Python). The
  `SINGULARITY_IMAGE` constant is now `SIF_IMAGE`.
- **Breaking:** the internal modules were reorganised. `presurfer.spm_workflows`
  and `presurfer.public_api` no longer exist. Import the four workflow functions
  from `presurfer`.

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
- Docker and Apptainer runtimes for SPM25 Standalone.
- MIT licence, type information (`py.typed`), and continuous integration.

### Notes

- Results have not yet been numerically validated against the historical
  SPM12/MATLAB pipeline.
