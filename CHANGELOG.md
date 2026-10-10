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

The first PyPI release and a substantial rewrite of the earlier `prathama`
release (package version 0.1.0). Every SPM step now runs in a container, so the
whole pipeline works without MATLAB.

### Changed

- **Breaking:** the workflow commands were renamed. Scripts that use the old
  names need updating.

  | Before (`prathama`) | Now |
  | --- | --- |
  | `presurf_biascorrect` | `biascorrect` |
  | `presurf_MPRAGEise` | `MPRAGEise` |
  | `presurf_INV2` | `stripmask` |
  | `presurf_UNI` | `brainmask` |

- Each run writes into a new timestamped directory, so repeated runs never
  overwrite earlier results.
- Python 3.11 or later is required (the earlier release accepted 3.10).
- The package no longer installs a top-level `scripts` module. Use
  `presurfer.command_line:main` instead of `scripts.presurfer_box:main`.
- The Python functions return the `Path` of the output directory (or, for
  `spm_mprageise`, of the MPRAGEised image), now inside the timestamped run
  directory. `image=` and `runtime=` are keyword-only.
- Problems such as a missing container, a missing image, or a failed SPM job
  raise `RuntimeError` with a message that says how to fix it.

### Added

- First PyPI release, published through trusted publishing: `pip install presurfer`.
- Click command-line interface with `-h`/`--help` on every command and a
  `--check` option that verifies the selected container and reports the SPM
  version.
- `spm_biascorrect`, `spm_mprageise`, `spm_stripmask`, and `spm_seg` Python
  functions, importable from `presurfer`.
- Docker and Apptainer runtimes for SPM25 Standalone.
- MIT licence, citation metadata, type information (`py.typed`), automated
  tests, and continuous integration.

### Notes

- Results have not yet been numerically validated against the historical
  SPM12/MATLAB pipeline.
