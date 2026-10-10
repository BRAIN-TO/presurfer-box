# presurfer-box [![Version](https://img.shields.io/badge/version-2.0.0-purple.svg)](https://github.com/srikash/presurfer-box/releases/tag/v2.0.0) [![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE) [![CI](https://github.com/srikash/presurfer-box/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/srikash/presurfer-box/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/1350566808.svg)](https://doi.org/10.5281/zenodo.22163094)

MATLAB-free MP2RAGE preprocessing for [presurfer](https://github.com/srikash/presurfer),
using SPM Standalone in a Docker, Singularity, or Apptainer container.

`presurfer-box` makes the presurfer steps (bias correction, MPRAGEising, strip
masks, and brain masks) available as a Python package and command-line tool. You
do not need MATLAB, a MATLAB licence, or a local SPM installation. SPM runs
inside the
[official SPM Standalone container](https://github.com/spm/spm-docker), and
Python prepares the files and runs the container for you.

> **Status:** This version uses SPM25 Standalone. Results have not yet been
> numerically validated against the historical SPM12/MATLAB pipeline.

## Table of contents

- [What changed in 2.0.0](#what-changed-in-200)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Choosing a workflow](#choosing-a-workflow)
- [Python API](#python-api)
- [Outputs](#outputs)
- [Legacy MATLAB implementation](#legacy-matlab-implementation)
- [Reproducibility and validation](#reproducibility-and-validation)
- [Licence](#licence)
- [Citation](#citation)

## What changed in 2.0.0

Version 2.0.0 is the first release on PyPI and a substantial rewrite of the
`prathama` release (package version 0.1.0). The main change is that every SPM
step now runs in a container, so the whole pipeline works without MATLAB.

**Installation**

- Install with `pip install presurfer`. You no longer need to clone the
  repository.
- Python 3.11 or later is required (the earlier release accepted 3.10).
- You still need Docker, Singularity, or Apptainer, plus the SPM container image.
  `presurfer-box --check` tells you whether they are set up correctly.

**Command line**

- The commands were renamed. Scripts that use the old names need updating:

  | Before (`prathama`) | Now |
  | --- | --- |
  | `presurf_biascorrect` | `biascorrect` |
  | `presurf_MPRAGEise` | `MPRAGEise` |
  | `presurf_INV2` | `stripmask` |
  | `presurf_UNI` | `brainmask` |

- The interface is built with Click, so `-h` and `--help` work on every command.
- `--check` verifies the selected container and prints the SPM version.
- Each run writes into a new timestamped directory, so repeated runs never
  overwrite earlier results.

**Python API**

- The four functions keep their names: `spm_biascorrect`, `spm_mprageise`,
  `spm_stripmask`, and `spm_seg`. Import them from `presurfer`.
- Each returns the `Path` of the output directory (or, for `spm_mprageise`, of
  the MPRAGEised image). That directory now sits inside a new timestamped run
  directory, so use the returned path instead of guessing where results went.
- `image=` and `runtime=` are keyword-only, and `runtime` accepts only
  `"docker"` or `"singularity"`.
- Problems such as a missing container, a missing image, or a failed SPM job raise
  `RuntimeError` with a message that says how to fix it.
- Only the names imported from `presurfer` itself are public. Do not rely on the
  internal modules.
- The package no longer installs a top-level `scripts` module. Use
  `presurfer.command_line:main` instead of `scripts.presurfer_box:main`.

**Project**

- MIT licence, citation metadata, and a changelog.
- Automated tests and continuous integration, with releases published to PyPI.

See the [changelog](CHANGELOG.md) for the complete list.

## Installation

`presurfer-box` requires Python 3.11+ and one container runtime: Docker,
Singularity, or Apptainer. It is a standard `pyproject.toml` package, so install
it with whichever of these you already use.

### venv

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install presurfer
presurfer-box --help
```

### conda / mamba

`presurfer` comes from PyPI, not conda-forge, so `pip install` does the actual
install inside a conda or mamba environment:

```bash
conda create -n presurfer python=3.11
conda activate presurfer
pip install presurfer
presurfer-box --help
```

(`mamba` is a drop-in replacement for `conda` in both commands above.)

### From a source checkout

```bash
git clone https://github.com/srikash/presurfer-box.git
cd presurfer-box
pip install .            # or: pip install -e . for an editable install
```

The legacy MATLAB source is optional. Fetch its pinned submodule only if you
need to inspect or run the historical implementation:

```bash
git submodule update --init --recursive
```

### uv

Included because this project's development and CI use
[uv](https://docs.astral.sh/uv/). It is not required for everyday use.

```bash
# from PyPI, into an isolated tool environment
uv tool install --python 3.11 presurfer
presurfer-box --help

# from a source checkout
cd presurfer-box
uv sync
uv run presurfer-box --help
```

### The SPM container

The Python package does not include SPM. Download the official container once,
then check that `presurfer-box` can use it.

**Docker**

```bash
docker pull ghcr.io/spm/spm-docker:docker-matlab-25.01.02
presurfer-box --check
```

**Singularity / Apptainer** (for example on an HPC cluster)

```bash
singularity pull --name spm.sif \
  oras://ghcr.io/spm/spm-docker:singularity-matlab-25.01.02

presurfer-box --sif spm.sif --check
```

`apptainer pull` works in the same way. A successful check prints the runtime,
the image, and the SPM version.

## Quick start

```bash
# Create a bias-corrected image and bias field
presurfer-box biascorrect IMAGE.nii

# Create MPRAGEised UNI
presurfer-box MPRAGEise INV2.nii UNI.nii

# Create an INV2-derived strip mask
presurfer-box stripmask INV2.nii

# Create UNI tissue classes, brain mask, and white-matter mask
presurfer-box brainmask UNI.nii
```

Inputs can be `.nii` or `.nii.gz`. Docker is the default runtime. To use a local
Singularity or Apptainer image, pass `--sif` before the command:

```bash
presurfer-box --sif spm.sif stripmask INV2.nii
```

To use a different Docker image, pass `--image IMAGE` instead. `--image` and
`--sif` cannot be combined.

## Choosing a workflow

| Need | CLI command | Python function | Main output |
| --- | --- | --- | --- |
| Bias-correct an image | `biascorrect IMAGE` | `spm_biascorrect()` | Bias-corrected image and bias field |
| Create MPRAGEised UNI | `MPRAGEise INV2 UNI` | `spm_mprageise()` | `*_MPRAGEised.nii` |
| Create a strip mask | `stripmask INV2` | `spm_stripmask()` | `*_stripmask.nii` |
| Create UNI-derived masks | `brainmask UNI` | `spm_seg()` | Tissue classes, brain mask, and white-matter mask |

`MPRAGEise` bias-corrects INV2 in a temporary directory, rescales the corrected
INV2 to the range 0 to 1, and multiplies it voxel by voxel with UNI. It does not
run the strip-mask workflow, so run `stripmask` separately if you need the mask.

## Python API

```python
from presurfer import spm_biascorrect, spm_mprageise, spm_seg, spm_stripmask

spm_biascorrect("INV2.nii")
spm_mprageise("INV2.nii", "UNI.nii")
spm_stripmask("INV2.nii")
spm_seg("UNI.nii")
```

Every function accepts the optional keywords `image=` and `runtime=`. For
Singularity or Apptainer, pass the local SIF path as `image=`:

```python
spm_stripmask("INV2.nii", image="spm.sif", runtime="singularity")
```

`spm_biascorrect`, `spm_stripmask`, and `spm_seg` return the path of the
`presurf_*` output directory. `spm_mprageise` returns the path of the
`*_MPRAGEised.nii` image. All of them raise `RuntimeError` if the container is
unavailable or SPM fails.

## Outputs

Each run creates a new UTC timestamped directory beside its input, containing one
`presurf_*` directory for the workflow. The `biascorrect`, `stripmask`, and
`brainmask` workflows also save the SPM output as `spm.log`:

```text
YYMMDDThh:mm:ss_presurfer/
├── spm.log
└── presurf_INV2/      # or presurf_UNI, presurf_biascorrect, presurf_MPRAGEise
```

For example, `250101T12:34:56_presurfer/presurf_INV2/`. If two runs start in the
same second, the second directory gets a numeric suffix (`-2`). `MPRAGEise` uses a
temporary `tmp_` directory for its bias-correction step and removes it
afterwards.

Compressed `.nii.gz` inputs are supported. The source file is never changed, and
the workflow writes an uncompressed working copy into its output directory.

## Legacy MATLAB implementation

The original MATLAB implementation lives in
[srikash/presurfer](https://github.com/srikash/presurfer) and remains available
here as a pinned Git submodule:

```text
src/matlab/presurfer
```

For MATLAB use:

```matlab
addpath('src/matlab/presurfer/func')
```

Update the submodule only when intentionally adopting a newer original
presurfer commit (unlikely to happen).

## Reproducibility and validation

- Default image: `ghcr.io/spm/spm-docker:docker-matlab-25.01.02`
- SPM runtime: SPM25 Standalone
- Historical implementation: SPM12 with MATLAB
- Numerical equivalence with the historical pipeline has not yet been validated
  against reference NIfTI data.
- The MPRAGEise multiplication is reimplemented with NumPy and NiBabel. It
  follows the original `mat2gray(INV2) .* UNI` calculation but also needs
  validation on representative data.

## Licence

MIT. See [LICENSE](LICENSE).

## Citation

See [CITATION.cff](CITATION.cff).
