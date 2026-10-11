"""Public presurfer workflows composed from SPM processing steps."""

import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from rich.console import Console

from presurfer.container_runtime import (
    IMAGE,
    SIF_IMAGE,
    Container,
    Runtime,
    run_spm_batch,
)
from presurfer.output_paths import (
    container_path,
    materialise_input,
    nii_stem,
    utc_run_directory,
)
from presurfer.spm_batch_scripts import default_threads, imcalc_job, segmentation_job

Kind = Literal["biascorrect", "UNI", "INV2"]
StageReporter = Callable[[str], None]
LOGGER = logging.getLogger(__name__)
CONSOLE = Console()

__all__ = [
    "IMAGE",
    "SIF_IMAGE",
    "presurf_biascorrect",
    "presurf_mprageise",
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


def rename_segmentation(out: Path, stem: str, classes: tuple[int, ...]) -> None:
    """Rename SPM segmentation outputs to presurfer output names.

    Args:
        out: Directory containing SPM-produced segmentation files.
        stem: NIfTI basename without its extension.
        classes: Native tissue-class numbers retained by the workflow.
    """
    for produced, suffix in (
        (f"m{stem}.nii", "_biascorrected.nii"),
        (f"BiasField_{stem}.nii", "_biasfield.nii"),
    ):
        (out / produced).replace(out / f"{stem}{suffix}")
    for number in classes:
        (out / f"c{number}{stem}.nii").replace(out / f"{stem}_class{number}.nii")
    (out / f"{stem}_seg8.mat").unlink(missing_ok=True)


def run_segmentation(
    source: Path,
    kind: Kind,
    container: Container,
    *,
    threads: int | None = None,
    temporary: bool = False,
    reporter: StageReporter | None = None,
) -> Path:
    """Run one configured presurfer SPM segmentation workflow.

    Args:
        source: Input ``.nii`` or ``.nii.gz`` file.
        kind: Workflow name: ``"biascorrect"``, ``"UNI"``, or ``"INV2"``.
        container: Runtime and image to run SPM in.
        threads: Number of MATLAB computational threads, or ``None`` to keep
            the MATLAB default.
        temporary: Whether the run directory is an automatically removed stage.
        reporter: Optional recipient for progress messages.

    Returns:
        Created ``presurf_<kind>`` output directory.

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
    run_dir = utc_run_directory(source.parent, temporary)
    out = run_dir / f"presurf_{kind}"
    out.mkdir()
    report_stage(reporter, f"Prepared output directory {run_dir}", started)
    copied = materialise_input(source, out)
    mount_root = source.parent
    input_in_container = container_path(copied, mount_root)
    out_in_container = container_path(out, mount_root)
    job = out / ".presurfer_segmentation.m"
    job.write_text(
        segmentation_job(
            input_in_container, out_in_container, spec.native, spec.samp, threads
        )
    )
    try:
        report_stage(reporter, "Running SPM segmentation", started)
        run_spm_batch(mount_root, job, container, run_dir / "spm.log", threads)
    finally:
        job.unlink(missing_ok=True)
    stem = nii_stem(copied)
    rename_segmentation(out, stem, spec.classes)
    report_stage(reporter, "Processed segmentation outputs", started)
    for mask in spec.masks:
        job = out / ".presurfer_imcalc.m"
        inputs = [
            container_path(out / f"{stem}_class{number}.nii", mount_root)
            for number in mask.classes
        ]
        output = container_path(out / f"{stem}{mask.suffix}", mount_root)
        batch_file = container_path(out / f"{stem}{mask.batch_suffix}", mount_root)
        job.write_text(imcalc_job(inputs, output, mask.expression, batch_file, threads))
        try:
            report_stage(reporter, f"Generating {mask.suffix}", started)
            run_spm_batch(mount_root, job, container, run_dir / "spm.log", threads)
        finally:
            job.unlink(missing_ok=True)
    report_stage(reporter, "Workflow complete", started)
    return out


def mprageise(
    inv2: Path,
    uni: Path,
    container: Container,
    *,
    threads: int | None = None,
    reporter: StageReporter | None = None,
) -> Path:
    """Create an MPRAGEised UNI image from INV2 and UNI acquisitions.

    The workflow bias-corrects INV2 with SPM, min-max normalises the resulting
    image, and multiplies it voxelwise with UNI.

    Args:
        inv2: INV2 ``.nii`` or ``.nii.gz`` input file.
        uni: UNI ``.nii`` or ``.nii.gz`` input file.
        container: Runtime and image to run SPM in.
        threads: Number of MATLAB computational threads, or ``None`` to keep
            the MATLAB default.
        reporter: Optional recipient for progress messages.

    Returns:
        Path to the generated ``*_MPRAGEised.nii`` image.

    Raises:
        RuntimeError: If SPM bias correction fails or NumPy/NiBabel is absent.
    """
    started = time.monotonic()
    inv2 = inv2.resolve()
    uni = uni.resolve()
    if not inv2.is_file() or not uni.is_file():
        raise RuntimeError("Both INV2 and UNI inputs must be existing files.")
    nii_stem(inv2)
    nii_stem(uni)
    report_stage(reporter, "Validated MPRAGEise inputs", started)
    bias_dir = run_segmentation(
        inv2,
        "biascorrect",
        container,
        threads=threads,
        temporary=True,
        reporter=reporter,
    )
    try:
        import nibabel as nib
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "MPRAGEise needs numpy and nibabel. Install project dependencies with uv sync."
        ) from None
    run_dir = utc_run_directory(uni.parent)
    output_dir = run_dir / "presurf_MPRAGEise"
    output_dir.mkdir()
    try:
        uni_local = materialise_input(uni, output_dir)
        inv2_bias = bias_dir / f"{nii_stem(inv2)}_biascorrected.nii"
        uni_img = cast("nib.Nifti1Image", nib.load(str(uni_local)))
        inv2_img = cast("nib.Nifti1Image", nib.load(str(inv2_bias)))
        uni_data = uni_img.get_fdata(dtype=np.float64)
        inv2_data = inv2_img.get_fdata(dtype=np.float64)
        if uni_data.shape != inv2_data.shape:
            raise RuntimeError("INV2 and UNI images must have matching dimensions.")
        if not np.allclose(uni_img.affine, inv2_img.affine):
            raise RuntimeError(
                "INV2 and UNI images must have matching spatial affines."
            )
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
    finally:
        shutil.rmtree(bias_dir.parent, ignore_errors=True)
        report_stage(reporter, "Removed temporary bias-correction stage", started)


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
    return run_segmentation(
        Path(input_file),
        "biascorrect",
        Container(runtime, image),
        threads=default_threads() if threads is None else threads,
    )


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
    return mprageise(
        Path(inv2_file),
        Path(uni_file),
        Container(runtime, image),
        threads=default_threads() if threads is None else threads,
    )


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
    return run_segmentation(
        Path(input_file),
        "INV2",
        Container(runtime, image),
        threads=default_threads() if threads is None else threads,
    )


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
    return run_segmentation(
        Path(input_file),
        "UNI",
        Container(runtime, image),
        threads=default_threads() if threads is None else threads,
    )
