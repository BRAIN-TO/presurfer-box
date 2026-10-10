# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - Unreleased

### Added

- `biascorrect`, `MPRAGEise`, `stripmask`, and `brainmask` commands, with
  matching `spm_biascorrect`, `spm_mprageise`, `spm_stripmask`, and `spm_seg`
  Python functions.
- Docker, Singularity, and Apptainer runtimes for SPM25 Standalone.
- `--check` option that verifies the selected container and reports the SPM
  version.

### Notes

- Results have not yet been numerically validated against the historical
  SPM12/MATLAB pipeline.
