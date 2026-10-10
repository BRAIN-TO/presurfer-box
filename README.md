# presurfer-box [![Version](https://img.shields.io/badge/version-2.5.0-purple.svg)](https://github.com/srikash/presurfer-box/releases/tag/v2.5.0) [![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE) [![CI](https://github.com/srikash/presurfer-box/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/srikash/presurfer-box/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/1350566808.svg)](https://doi.org/10.5281/zenodo.22163094)

MATLAB-free MP2RAGE preprocessing for [presurfer](https://github.com/srikash/presurfer),
using SPM Standalone in a Docker or Apptainer container.

`presurfer-box` makes the presurfer steps (bias correction, MPRAGEising, strip
masks, and brain masks) available as a Python package and command-line tool. You
do not need MATLAB, a MATLAB licence, or a local SPM installation. SPM runs
inside the
[official SPM Standalone container](https://github.com/spm/spm-docker), and
Python prepares the files and runs the container for you.

> **Status:** This version uses SPM25 Standalone. Results have not yet been
> numerically validated against the historical SPM12/MATLAB pipeline.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Choosing a workflow](#choosing-a-workflow)
- [Python API](#python-api)
- [Outputs](#outputs)
- [Legacy MATLAB implementation](#legacy-matlab-implementation)
- [Reproducibility and validation](#reproducibility-and-validation)
- [Licence](#licence)
- [Changelog](#changelog)
- [Citation](#citation)

## Installation

The command is `presurfer`. The older name `presurfer-box` also works.

`presurfer-box` requires Python 3.11+ and one container runtime: Docker,
or Apptainer. It is a standard `pyproject.toml` package, so install
it with whichever of these you already use.

### venv

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install presurfer
presurfer --help
```

### conda / mamba

`presurfer` comes from PyPI, not conda-forge, so `pip install` does the actual
install inside a conda or mamba environment:

```bash
conda create -n presurfer python=3.11
conda activate presurfer
pip install presurfer
presurfer --help
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
presurfer --help

# from a source checkout
cd presurfer-box
uv sync
uv run presurfer --help
```

### The SPM container

The Python package does not include SPM. Download the official container once,
then check that `presurfer` can use it.

**Docker**

```bash
docker pull ghcr.io/spm/spm-docker:docker-matlab-25.01.02
presurfer --check
```

**Apptainer** (for example on an HPC cluster)

```bash
apptainer pull --name spm.sif \
  oras://ghcr.io/spm/spm-docker:singularity-matlab-25.01.02

presurfer --engine apptainer --sif spm.sif --check
```

A successful check prints the runtime,
the image, and the SPM version.

## Quick start

```bash
# Create a bias-corrected image and bias field
presurfer biascorrect IMAGE.nii

# Create MPRAGEised UNI
presurfer MPRAGEise INV2.nii UNI.nii

# Create an INV2-derived strip mask
presurfer stripmask INV2.nii

# Create UNI tissue classes, brain mask, and white-matter mask
presurfer brainmask UNI.nii
```

Inputs can be `.nii` or `.nii.gz`. Docker is the default runtime. To use a local
Apptainer image, pass `--engine apptainer --sif IMAGE` before the command:

```bash
presurfer --engine apptainer --sif spm.sif stripmask INV2.nii
```

To use a different Docker image, pass `--image IMAGE` instead. `--image` and
`--sif` cannot be combined.

### Container engine

`--engine` chooses between `docker` (the default) and `apptainer`. Apptainer
needs a local SIF file, so `--engine apptainer` must be used with `--sif`.
Passing `--sif` alone selects Apptainer automatically.

```bash
presurfer --engine apptainer --sif spm.sif brainmask UNI.nii
```

### Threads

The MATLAB Runtime inside the SPM container starts with a single thread, so SPM
would otherwise use one core however many the machine has. `presurfer` sets
the thread count for every SPM step. By default it uses the number of available
cores, but never fewer than 8 and never more than 16, because extra threads stop
helping beyond a certain point. Choose a number yourself with `--threads`:

```bash
presurfer --threads 12 brainmask UNI.nii
```

In Python, pass `threads=12` to any workflow function.

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

Every function accepts the optional keywords `image=`, `runtime=`, and
`threads=`. For
Apptainer, pass the local SIF path as `image=`:

```python
spm_stripmask("INV2.nii", image="spm.sif", runtime="apptainer")
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

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Citation

See [CITATION.cff](CITATION.cff).
