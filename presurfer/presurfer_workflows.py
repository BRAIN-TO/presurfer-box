"""Public presurfer workflows composed from SPM processing steps."""

import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import nibabel as nib
import numpy as np
from rich.console import Console

from presurfer.container_runtime import IMAGE, SIF_IMAGE, Container, Runtime
from presurfer.output_paths import materialise_input, nii_stem, utc_run_directory
from presurfer.spm_runner import ContainerRunner, SegmentationFiles, SpmRunner

Kind = Literal["biascorrect", "UNI", "INV2"]
StageReporter = Callable[[str], None]
LOGGER = logging.getLogger(__name__)
CONSOLE = Console()

__all__ = [
    "IMAGE",
    "SIF_IMAGE",
    "presurf_biascorrect",
    "presurf_mprageise",
    "presurf_recon_prep",
    "presurf_seg",
    "presurf_stripmask",
]


@dataclass(frozen=True)
class MaskSpec:
    """An image-calculator step that turns tissue classes into a mask.

    Attributes:
        classes: Tissue-class numbers combined by the expression.
        suffix: Output filename suffix, including the extension.
        expression: SPM Image Calculator expression using ``i1``, ``i2``, etc.
        batch_suffix: Suffix of the saved ``matlabbatch`` MAT file.
    """

    classes: tuple[int, ...]
    suffix: str
    expression: str
    batch_suffix: str


@dataclass(frozen=True)
class WorkflowSpec:
    """SPM settings for one segmentation-based workflow.

    Attributes:
        native: Six flags selecting native tissue-class outputs.
        samp: Segmentation sampling distance in millimetres.
        classes: Native tissue-class numbers kept in the output directory.
        masks: Mask steps run after segmentation, in order.
    """

    native: list[int]
    samp: int
    classes: tuple[int, ...]
    masks: tuple[MaskSpec, ...]


WORKFLOWS: dict[Kind, WorkflowSpec] = {
    "biascorrect": WorkflowSpec([0] * 6, 3, (), ()),
    "UNI": WorkflowSpec(
        [1, 1, 1, 0, 0, 0],
        2,
        (1, 2, 3),
        (
            MaskSpec(
                (1, 2, 3), "_brainmask.nii", "(i1+i2+i3)>0.3", "_presurfStripBatch.mat"
            ),
            MaskSpec((2,), "_WMmask.nii", "(i1)>0.5", "_presurfWMBatch.mat"),
        ),
    ),
    "INV2": WorkflowSpec(
        [0, 0, 1, 1, 1, 1],
        2,
        (3, 4, 5, 6),
        (
            MaskSpec(
                (3, 4, 5, 6),
                "_stripmask.nii",
                "1-((i1+i2+i3+i4)>0.5)",
                "_presurfStripBatch.mat",
            ),
        ),
    ),
}


def report_stage(reporter: StageReporter | None, message: str, started: float) -> None:
    """Log and display a workflow stage with elapsed time.

    Args:
        reporter: Optional callback that receives the message. When it is
            ``None``, the message is printed to the console.
        message: Description of the stage.
        started: Workflow start time from ``time.monotonic()``.
    """
    rendered = f"{message} ({time.monotonic() - started:.1f}s)"
    LOGGER.info(rendered)
    if reporter is not None:
        reporter(rendered)
    else:
        CONSOLE.print(f"[cyan]{rendered}[/cyan]")


def _run_workflow(
    source: Path,
    kind: Kind,
    runner: SpmRunner,
    *,
    temporary: bool = False,
    run_dir: Path | None = None,
    reporter: StageReporter | None = None,
) -> tuple[Path, SegmentationFiles]:
    """Run one configured presurfer SPM segmentation workflow.

    Args:
        source: Input ``.nii`` or ``.nii.gz`` file.
        kind: Workflow name: ``"biascorrect"``, ``"UNI"``, or ``"INV2"``.
        runner: Runs the SPM steps.
        temporary: Whether the run directory is an automatically removed stage.
        run_dir: Existing run directory to write into, so that several
            workflows can share one. By default a new timestamped directory is
            created beside ``source``.
        reporter: Optional recipient for progress messages.

    Returns:
        The created ``presurf_<kind>`` output directory and the segmentation
        files in it.

    Raises:
        RuntimeError: If input validation, container execution, or expected SPM
            output handling fails.
    """
    spec = WORKFLOWS[kind]
    started = time.monotonic()
    source = source.resolve()
    if not source.is_file():
        raise RuntimeError(f"Input file does not exist: {source}")
    nii_stem(source)
    report_stage(reporter, "Validated input", started)
    if run_dir is None:
        run_dir = utc_run_directory(source.parent, temporary)
    out = run_dir / f"presurf_{kind}"
    out.mkdir()
    report_stage(reporter, f"Prepared output directory {run_dir}", started)
    copied = materialise_input(source, out)
    report_stage(reporter, "Running SPM segmentation", started)
    files = runner.segment(copied, spec.native, spec.samp, spec.classes)
    report_stage(reporter, "Processed segmentation outputs", started)
    stem = nii_stem(copied)
    for mask in spec.masks:
        report_stage(reporter, f"Generating {mask.suffix}", started)
        runner.image_calc(
            [files.classes[number] for number in mask.classes],
            out / f"{stem}{mask.suffix}",
            mask.expression,
            out / f"{stem}{mask.batch_suffix}",
        )
    report_stage(reporter, "Workflow complete", started)
    return out, files


def run_segmentation(
    source: Path,
    kind: Kind,
    runner: SpmRunner,
    *,
    reporter: StageReporter | None = None,
) -> Path:
    """Run one presurfer SPM segmentation workflow in a new run directory.

    Args:
        source: Input ``.nii`` or ``.nii.gz`` file.
        kind: Workflow name: ``"biascorrect"``, ``"UNI"``, or ``"INV2"``.
        runner: Runs the SPM steps.
        reporter: Optional recipient for progress messages.

    Returns:
        Created ``presurf_<kind>`` output directory.

    Raises:
        RuntimeError: If input validation, container execution, or expected SPM
            output handling fails.
    """
    return _run_workflow(source, kind, runner, reporter=reporter)[0]


def _check_matching_grids(inv2: Path, uni: Path) -> None:
    """Check that INV2 and UNI share a voxel grid, reading headers only.

    Args:
        inv2: INV2 ``.nii`` or ``.nii.gz`` file.
        uni: UNI ``.nii`` or ``.nii.gz`` file.

    Raises:
        RuntimeError: If the image dimensions or spatial affines differ.
    """
    inv2_img = cast("nib.Nifti1Image", nib.load(str(inv2)))
    uni_img = cast("nib.Nifti1Image", nib.load(str(uni)))
    if inv2_img.shape != uni_img.shape:
        raise RuntimeError("INV2 and UNI images must have matching dimensions.")
    if not np.allclose(inv2_img.affine, uni_img.affine):
        raise RuntimeError("INV2 and UNI images must have matching spatial affines.")


def _combine_mprageise(
    inv2_biascorrected: Path,
    uni: Path,
    output_dir: Path,
    reporter: StageReporter | None,
    started: float,
) -> Path:
    """Multiply a normalised bias-corrected INV2 voxelwise with UNI.

    Args:
        inv2_biascorrected: Bias-corrected INV2 ``.nii`` file.
        uni: UNI ``.nii`` or ``.nii.gz`` input file.
        output_dir: Existing directory that receives the MPRAGEised image.
        reporter: Optional recipient for progress messages.
        started: Workflow start time from ``time.monotonic()``.

    Returns:
        Path to the generated ``*_MPRAGEised.nii`` image.

    Raises:
        RuntimeError: If the images differ in dimensions or affine, or INV2
            has no finite voxels.
    """
    uni_local = materialise_input(uni, output_dir)
    uni_img = cast("nib.Nifti1Image", nib.load(str(uni_local)))
    inv2_img = cast("nib.Nifti1Image", nib.load(str(inv2_biascorrected)))
    uni_data = uni_img.get_fdata(dtype=np.float64)
    inv2_data = inv2_img.get_fdata(dtype=np.float64)
    if uni_data.shape != inv2_data.shape:
        raise RuntimeError("INV2 and UNI images must have matching dimensions.")
    if not np.allclose(uni_img.affine, inv2_img.affine):
        raise RuntimeError("INV2 and UNI images must have matching spatial affines.")
    if not np.isfinite(inv2_data).any():
        raise RuntimeError("Bias-corrected INV2 contains no finite voxel values.")
    report_stage(reporter, "Running MPRAGEise image calculation", started)
    minimum, maximum = np.nanmin(inv2_data), np.nanmax(inv2_data)
    normalised = (
        np.zeros_like(inv2_data)
        if maximum == minimum
        else (inv2_data - minimum) / (maximum - minimum)
    )
    output = output_dir / f"{nii_stem(uni)}_MPRAGEised.nii"
    nib.save(
        nib.Nifti1Image(uni_data * normalised, uni_img.affine, uni_img.header),
        str(output),
    )
    report_stage(reporter, "MPRAGEise complete", started)
    return output


def mprageise(
    inv2: Path,
    uni: Path,
    runner: SpmRunner,
    *,
    reporter: StageReporter | None = None,
) -> Path:
    """Create an MPRAGEised UNI image from INV2 and UNI acquisitions.

    The workflow bias-corrects INV2 with SPM, min-max normalises the resulting
    image, and multiplies it voxelwise with UNI.

    Args:
        inv2: INV2 ``.nii`` or ``.nii.gz`` input file.
        uni: UNI ``.nii`` or ``.nii.gz`` input file.
        runner: Runs the SPM steps.
        reporter: Optional recipient for progress messages.

    Returns:
        Path to the generated ``*_MPRAGEised.nii`` image.

    Raises:
        RuntimeError: If SPM bias correction fails or the images do not match.
    """
    started = time.monotonic()
    inv2 = inv2.resolve()
    uni = uni.resolve()
    if not inv2.is_file() or not uni.is_file():
        raise RuntimeError("Both INV2 and UNI inputs must be existing files.")
    nii_stem(inv2)
    nii_stem(uni)
    report_stage(reporter, "Validated MPRAGEise inputs", started)
    bias_dir, bias_files = _run_workflow(
        inv2, "biascorrect", runner, temporary=True, reporter=reporter
    )
    run_dir = utc_run_directory(uni.parent)
    output_dir = run_dir / "presurf_MPRAGEise"
    output_dir.mkdir()
    try:
        return _combine_mprageise(
            bias_files.biascorrected, uni, output_dir, reporter, started
        )
    finally:
        shutil.rmtree(bias_dir.parent, ignore_errors=True)
        report_stage(reporter, "Removed temporary bias-correction stage", started)


def recon_prep(
    inv2: Path,
    uni: Path,
    runner: SpmRunner,
    *,
    reporter: StageReporter | None = None,
) -> Path:
    """Prepare INV2 and UNI for FreeSurfer in one run with two segmentations.

    The strip-mask segmentation of INV2 also produces a bias-corrected INV2.
    That image is reused for MPRAGEise, so no separate bias-correction run is
    needed. The brain-mask segmentation then runs on the MPRAGEised UNI.

    All three workflows write into one timestamped run directory.

    Args:
        inv2: INV2 ``.nii`` or ``.nii.gz`` input file.
        uni: UNI ``.nii`` or ``.nii.gz`` input file.
        runner: Runs the SPM steps.
        reporter: Optional recipient for progress messages.

    Returns:
        Run directory holding ``presurf_INV2``, ``presurf_MPRAGEise``, and
        ``presurf_UNI``.

    Raises:
        RuntimeError: If an input is missing or not a NIfTI file, the images do
            not share a voxel grid, or SPM fails.
    """
    started = time.monotonic()
    inv2 = inv2.resolve()
    uni = uni.resolve()
    if not inv2.is_file() or not uni.is_file():
        raise RuntimeError("Both INV2 and UNI inputs must be existing files.")
    nii_stem(inv2)
    nii_stem(uni)
    _check_matching_grids(inv2, uni)
    report_stage(reporter, "Validated recon-prep inputs", started)
    run_dir = utc_run_directory(inv2.parent)
    _, inv2_files = _run_workflow(
        inv2, "INV2", runner, run_dir=run_dir, reporter=reporter
    )
    output_dir = run_dir / "presurf_MPRAGEise"
    output_dir.mkdir()
    mprageised = _combine_mprageise(
        inv2_files.biascorrected, uni, output_dir, reporter, started
    )
    _run_workflow(mprageised, "UNI", runner, run_dir=run_dir, reporter=reporter)
    report_stage(reporter, "recon-prep complete", started)
    return run_dir


def presurf_biascorrect(
    input_file: str | Path,
    *,
    image: str = IMAGE,
    runtime: Runtime = "docker",
    threads: int | None = None,
) -> Path:
    """Run SPM bias correction.

    Args:
        input_file: Path to a ``.nii`` or ``.nii.gz`` image.
        image: Docker image tag or local Apptainer image path. Defaults to the
            pinned official SPM25 Docker image.
        runtime: ``"docker"`` or ``"apptainer"``. Defaults to ``"docker"``.
        threads: Number of MATLAB computational threads. Defaults to the number
            of available cores, between 8 and 16.

    Returns:
        Path to the ``presurf_biascorrect`` output directory.

    Raises:
        RuntimeError: If input validation or SPM execution fails.
    """
    runner = ContainerRunner(Container(runtime, image), threads)
    return run_segmentation(Path(input_file), "biascorrect", runner)


def presurf_mprageise(
    inv2_file: str | Path,
    uni_file: str | Path,
    *,
    image: str = IMAGE,
    runtime: Runtime = "docker",
    threads: int | None = None,
) -> Path:
    """Create an MPRAGEised UNI image.

    Args:
        inv2_file: Path to the INV2 ``.nii`` or ``.nii.gz`` image.
        uni_file: Path to the UNI ``.nii`` or ``.nii.gz`` image.
        image: Docker image tag or local Apptainer image path. Defaults to the
            pinned official SPM25 Docker image.
        runtime: ``"docker"`` or ``"apptainer"``. Defaults to ``"docker"``.
        threads: Number of MATLAB computational threads. Defaults to the number
            of available cores, between 8 and 16.

    Returns:
        Path to the generated ``*_MPRAGEised.nii`` image.

    Raises:
        RuntimeError: If SPM bias correction or image processing fails.
    """
    runner = ContainerRunner(Container(runtime, image), threads)
    return mprageise(Path(inv2_file), Path(uni_file), runner)


def presurf_recon_prep(
    inv2_file: str | Path,
    uni_file: str | Path,
    *,
    image: str = IMAGE,
    runtime: Runtime = "docker",
    threads: int | None = None,
) -> Path:
    """Prepare INV2 and UNI for FreeSurfer with two SPM segmentations.

    Runs the strip-mask workflow on INV2, reuses its bias-corrected image for
    MPRAGEise, then runs the brain-mask workflow on the MPRAGEised UNI. This
    skips the separate bias-correction run that ``presurf_mprageise`` needs.

    The bias correction comes from the 2 mm strip-mask segmentation rather than
    the 3 mm sampling that ``presurf_mprageise`` uses, so the MPRAGEised image
    can differ slightly from the one that function produces.

    Args:
        inv2_file: Path to the INV2 ``.nii`` or ``.nii.gz`` image.
        uni_file: Path to the UNI ``.nii`` or ``.nii.gz`` image.
        image: Docker image tag or local Apptainer image path. Defaults to the
            pinned official SPM25 Docker image.
        runtime: ``"docker"`` or ``"apptainer"``. Defaults to ``"docker"``.
        threads: Number of MATLAB computational threads. Defaults to the number
            of available cores, between 8 and 16.

    Returns:
        Path to the run directory holding ``presurf_INV2``,
        ``presurf_MPRAGEise``, and ``presurf_UNI``.

    Raises:
        RuntimeError: If input validation or SPM execution fails.
    """
    runner = ContainerRunner(Container(runtime, image), threads)
    return recon_prep(Path(inv2_file), Path(uni_file), runner)


def presurf_stripmask(
    input_file: str | Path,
    *,
    image: str = IMAGE,
    runtime: Runtime = "docker",
    threads: int | None = None,
) -> Path:
    """Generate an INV2-derived non-brain strip mask.

    Args:
        input_file: Path to an INV2 ``.nii`` or ``.nii.gz`` image.
        image: Docker image tag or local Apptainer image path. Defaults to the
            pinned official SPM25 Docker image.
        runtime: ``"docker"`` or ``"apptainer"``. Defaults to ``"docker"``.
        threads: Number of MATLAB computational threads. Defaults to the number
            of available cores, between 8 and 16.

    Returns:
        Path to the ``presurf_INV2`` output directory, including the strip mask.

    Raises:
        RuntimeError: If input validation or SPM execution fails.
    """
    runner = ContainerRunner(Container(runtime, image), threads)
    return run_segmentation(Path(input_file), "INV2", runner)


def presurf_seg(
    input_file: str | Path,
    *,
    image: str = IMAGE,
    runtime: Runtime = "docker",
    threads: int | None = None,
) -> Path:
    """Generate UNI tissue-class, brain-mask, and WM-mask outputs.

    Args:
        input_file: Path to a UNI ``.nii`` or ``.nii.gz`` image.
        image: Docker image tag or local Apptainer image path. Defaults to the
            pinned official SPM25 Docker image.
        runtime: ``"docker"`` or ``"apptainer"``. Defaults to ``"docker"``.
        threads: Number of MATLAB computational threads. Defaults to the number
            of available cores, between 8 and 16.

    Returns:
        Path to the ``presurf_UNI`` output directory.

    Raises:
        RuntimeError: If input validation or SPM execution fails.
    """
    runner = ContainerRunner(Container(runtime, image), threads)
    return run_segmentation(Path(input_file), "UNI", runner)
