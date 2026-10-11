"""Run SPM steps on host files, hiding the container and its paths."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from presurfer.container_runtime import Container, run_spm_batch
from presurfer.output_paths import container_path, nii_stem
from presurfer.spm_batch_scripts import default_threads, imcalc_job, segmentation_job

__all__ = ["ContainerRunner", "SegmentationFiles", "SpmRunner"]


@dataclass(frozen=True)
class SegmentationFiles:
    """Files that a segmentation step leaves in its output directory.

    Attributes:
        biascorrected: Bias-corrected copy of the input image.
        biasfield: Estimated bias field.
        classes: Native tissue-class images, keyed by SPM class number.
    """

    biascorrected: Path
    biasfield: Path
    classes: dict[int, Path]


class SpmRunner(Protocol):
    """Runs SPM steps on files in a presurfer run directory.

    Every path is a host path. The output directory is the directory of the
    image or output file given to each call, and its parent is the run
    directory, which receives ``spm.log``.
    """

    def segment(
        self,
        image: Path,
        native: list[int],
        samp: int,
        keep_classes: tuple[int, ...],
    ) -> SegmentationFiles:
        """Run SPM Unified Segmentation on a NIfTI image.

        Args:
            image: Uncompressed ``.nii`` image inside the output directory.
            native: Six flags selecting native tissue-class outputs.
            samp: Segmentation sampling distance in millimetres.
            keep_classes: Tissue-class numbers to keep in the output directory.

        Returns:
            The files left in the output directory.
        """
        ...

    def image_calc(
        self,
        inputs: list[Path],
        output: Path,
        expression: str,
        batch_file: Path,
    ) -> Path:
        """Run the SPM Image Calculator.

        Args:
            inputs: Input NIfTI images.
            output: NIfTI file to create inside the output directory.
            expression: Expression using ``i1``, ``i2``, etc.
            batch_file: ``matlabbatch`` MAT file to save.

        Returns:
            The created ``output`` file.
        """
        ...


class ContainerRunner:
    """Runs SPM steps inside a Docker or Apptainer container.

    Attributes:
        container: Runtime and image to run SPM in.
        threads: Number of MATLAB computational threads.
    """

    def __init__(self, container: Container, threads: int | None = None) -> None:
        """Choose the container and thread count.

        Args:
            container: Runtime and image to run SPM in.
            threads: Number of MATLAB computational threads. Defaults to the
                number of available cores, between 8 and 16.
        """
        self.container = container
        self.threads = default_threads() if threads is None else threads

    def segment(
        self,
        image: Path,
        native: list[int],
        samp: int,
        keep_classes: tuple[int, ...],
    ) -> SegmentationFiles:
        """Run SPM Unified Segmentation and name its outputs for presurfer.

        Args:
            image: Uncompressed ``.nii`` image inside the output directory.
            native: Six flags selecting native tissue-class outputs.
            samp: Segmentation sampling distance in millimetres.
            keep_classes: Tissue-class numbers to keep in the output directory.

        Returns:
            The files left in the output directory.

        Raises:
            RuntimeError: If the container or SPM fails.
        """
        out = image.parent
        mount_root = out.parent.parent
        script = segmentation_job(
            container_path(image, mount_root),
            container_path(out, mount_root),
            native,
            samp,
            self.threads,
        )
        self._run(mount_root, out / ".presurfer_segmentation.m", script)
        return self._rename_outputs(out, nii_stem(image), keep_classes)

    def image_calc(
        self,
        inputs: list[Path],
        output: Path,
        expression: str,
        batch_file: Path,
    ) -> Path:
        """Run the SPM Image Calculator.

        Args:
            inputs: Input NIfTI images.
            output: NIfTI file to create inside the output directory.
            expression: Expression using ``i1``, ``i2``, etc.
            batch_file: ``matlabbatch`` MAT file to save.

        Returns:
            The created ``output`` file.

        Raises:
            RuntimeError: If the container or SPM fails.
        """
        out = output.parent
        mount_root = out.parent.parent
        script = imcalc_job(
            [container_path(path, mount_root) for path in inputs],
            container_path(output, mount_root),
            expression,
            container_path(batch_file, mount_root),
            self.threads,
        )
        self._run(mount_root, out / ".presurfer_imcalc.m", script)
        return output

    def _run(self, mount_root: Path, job: Path, script: str) -> None:
        """Write a job file, run it in the container, and always delete it.

        Args:
            mount_root: Host directory mounted at ``/data``.
            job: Where to write the job file, inside the output directory.
            script: MATLAB batch-script source.

        Raises:
            RuntimeError: If the container or SPM fails.
        """
        job.write_text(script)
        try:
            run_spm_batch(
                mount_root,
                job,
                self.container,
                job.parent.parent / "spm.log",
                self.threads,
            )
        finally:
            job.unlink(missing_ok=True)

    @staticmethod
    def _rename_outputs(
        out: Path, stem: str, keep_classes: tuple[int, ...]
    ) -> SegmentationFiles:
        """Rename SPM segmentation outputs to presurfer output names.

        Args:
            out: Directory containing SPM-produced segmentation files.
            stem: NIfTI basename without its extension.
            keep_classes: Native tissue-class numbers to keep.

        Returns:
            The renamed files.
        """
        biascorrected = out / f"{stem}_biascorrected.nii"
        biasfield = out / f"{stem}_biasfield.nii"
        (out / f"m{stem}.nii").replace(biascorrected)
        (out / f"BiasField_{stem}.nii").replace(biasfield)
        classes = {}
        for number in keep_classes:
            classes[number] = out / f"{stem}_class{number}.nii"
            (out / f"c{number}{stem}.nii").replace(classes[number])
        (out / f"{stem}_seg8.mat").unlink(missing_ok=True)
        return SegmentationFiles(biascorrected, biasfield, classes)
