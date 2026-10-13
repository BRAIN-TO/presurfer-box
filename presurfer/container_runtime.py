"""SPM container runtime commands and execution."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from presurfer.output_paths import container_path

IMAGE = "ghcr.io/spm/spm-docker:docker-matlab-25.01.02"
SIF_IMAGE = "spm.sif"
REGISTRY_SCHEMES = ("docker://", "oras://", "library://", "shub://")
Runtime = Literal["docker", "apptainer"]

__all__ = [
    "IMAGE",
    "SIF_IMAGE",
    "Container",
    "Runtime",
    "check_container",
    "container_command",
    "is_registry_image",
    "pull_sif",
    "run_spm_batch",
]


def _is_registry_name(image: str) -> bool:
    """Tell whether an Apptainer image is a bare registry name like ``ghcr.io/x:y``.

    Args:
        image: Image string given by the user.

    Returns:
        True if it has no URI scheme, is not an existing file, and does not end
        in ``.sif`` or ``.simg``.
    """
    return not (
        image.startswith(REGISTRY_SCHEMES)
        or image.endswith((".sif", ".simg"))
        or Path(image).is_file()
    )


def is_registry_image(image: str) -> bool:
    """Tell whether an image is a registry URI that Apptainer converts per run.

    Args:
        image: Image string held by a ``Container``.

    Returns:
        True for ``docker://``, ``oras://``, ``library://`` and ``shub://`` URIs.
    """
    return image.startswith(REGISTRY_SCHEMES)


@dataclass(frozen=True)
class Container:
    """A container runtime together with the image it runs.

    Attributes:
        runtime: ``"docker"`` or ``"apptainer"``.
        image: Docker image tag, or for Apptainer a local image path or registry
            URI. A bare registry name such as the default ``IMAGE`` gets a
            ``docker://`` prefix for Apptainer.

    Raises:
        RuntimeError: If ``runtime`` is not supported.
    """

    runtime: Runtime
    image: str

    def __post_init__(self) -> None:
        """Reject unsupported runtimes as soon as the container is created."""
        if self.runtime not in ("docker", "apptainer"):
            raise RuntimeError(
                f"Unsupported runtime: {self.runtime}. Use 'docker' or 'apptainer'."
            )
        if self.runtime == "apptainer" and _is_registry_name(self.image):
            object.__setattr__(self, "image", f"docker://{self.image}")


def _require_docker_image(image: str) -> None:
    """Check that Docker is installed and the image has been pulled.

    Args:
        image: Docker image tag.

    Raises:
        RuntimeError: If Docker is not on PATH or the image is not available
            locally.
    """
    if shutil.which("docker") is None:
        raise RuntimeError(
            "Docker was not found on PATH. Install Docker, then pull the SPM image."
        )
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode:
        raise RuntimeError(
            f"SPM image is not available locally: {image}\nPull it first: docker pull {image}"
        )


def _apptainer_executable(image: str) -> str:
    """Find Apptainer and check that a local image file exists.

    Registry images (``docker://``, ``oras://``, ...) are left for Apptainer to
    pull, so they are not checked.

    Args:
        image: Path to a local Apptainer image, or a registry URI.

    Returns:
        Path to the ``apptainer`` executable.

    Raises:
        RuntimeError: If Apptainer is not on PATH or the image file is missing.
    """
    executable = shutil.which("apptainer")
    if executable is None:
        raise RuntimeError("Apptainer was not found on PATH.")
    if not image.startswith(REGISTRY_SCHEMES) and not Path(image).is_file():
        raise RuntimeError(
            f"Apptainer image does not exist: {image}\n"
            f"Pull it first: apptainer pull --name {SIF_IMAGE} "
            "oras://ghcr.io/spm/spm-docker:singularity-matlab-25.01.02"
        )
    return executable


def pull_sif(image: str, output: Path, *, force: bool = False) -> Path:
    """Pull a registry image into a local Apptainer SIF file for reuse.

    Args:
        image: Registry URI such as ``docker://ghcr.io/...``.
        output: Path of the SIF file to write.
        force: Whether to overwrite an existing file.

    Returns:
        Path to the written SIF file.

    Raises:
        RuntimeError: If Apptainer is unavailable, the image is not a registry
            URI, the file exists without ``force``, or the pull fails.
    """
    if not image.startswith(REGISTRY_SCHEMES):
        raise RuntimeError(
            f"Not a registry image: {image}\n"
            "Use a URI such as docker://ghcr.io/spm/spm-docker:..."
        )
    executable = shutil.which("apptainer")
    if executable is None:
        raise RuntimeError("Apptainer was not found on PATH.")
    if output.exists() and not force:
        raise RuntimeError(f"{output} already exists. Use --force to overwrite it.")
    command = [executable, "pull"]
    if force:
        command.append("--force")
    command += [str(output), image]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise RuntimeError(f"apptainer pull failed (exit status {result.returncode}).")
    return output


def container_command(
    mount_root: Path, job_file: Path, container: Container
) -> list[str]:
    """Build a Docker or Apptainer SPM batch command.

    Args:
        mount_root: Host directory mounted at ``/data``.
        job_file: Generated SPM batch script below ``mount_root``.
        container: Runtime and image to run.

    Returns:
        Command arguments suitable for ``subprocess.run``.

    Raises:
        RuntimeError: If Apptainer is unavailable or the image file does not
            exist.
    """
    job = container_path(job_file, mount_root)
    if container.runtime == "docker":
        # The image has a home directory only for uid 1000. Any other uid gets
        # HOME=/, and MATLAB fails with fl:filesystem:AccessDenied.
        return [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{mount_root.resolve()}:/data",
            container.image,
            "batch",
            job,
        ]
    return [
        _apptainer_executable(container.image),
        "exec",
        "--bind",
        f"{mount_root.resolve()}:/data",
        container.image,
        "spm",
        "batch",
        job,
    ]


def check_container(container: Container) -> str:
    """Check that a selected SPM container can start and report its version.

    Args:
        container: Runtime and image to check.

    Returns:
        Human-readable runtime, image, and SPM version information.

    Raises:
        RuntimeError: If the runtime or image is unavailable, or SPM cannot
            start inside the selected container.
    """
    if container.runtime == "docker":
        _require_docker_image(container.image)
        command = [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            container.image,
            "--version",
        ]
        label = "Docker image"
    else:
        executable = _apptainer_executable(container.image)
        command = [executable, "exec", container.image, "spm", "--version"]
        label = f"{Path(executable).name.capitalize()} image"

    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"SPM container check failed (exit status {result.returncode})."
        raise RuntimeError(f"{message}\n{detail}" if detail else message)
    version = result.stdout.strip()
    return f"Runtime: {container.runtime}\n{label}: {container.image}\nSPM version:\n{version}"


def run_spm_batch(
    mount_root: Path,
    job_file: Path,
    container: Container,
    log_path: Path,
    threads: int | None = None,
) -> None:
    """Run a generated SPM batch in the selected container runtime.

    Each call appends a section to the log that records the container, image,
    and MATLAB thread count, followed by the captured output. Thread count can
    change results in the last digits, so the log lets a run be reproduced.

    Args:
        mount_root: Host directory mounted at ``/data``.
        job_file: Generated SPM batch script below ``mount_root``.
        container: Runtime and image to run.
        log_path: File that receives the captured standard output and error.
        threads: MATLAB thread count written into the batch script, recorded
            in the log. ``None`` means the MATLAB default.

    Raises:
        RuntimeError: If the runtime or image is unavailable, or the SPM batch
            exits unsuccessfully.
    """
    if container.runtime == "docker":
        _require_docker_image(container.image)
    command = container_command(mount_root, job_file, container)
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    header = (
        f"SPM batch: {job_file.name}\n"
        f"Container: {container.runtime} {container.image}\n"
        f"MATLAB threads: {threads if threads is not None else 'MATLAB default'}\n\n"
    )
    with log_path.open("a") as log:
        log.write(
            header
            + "STDOUT\n------\n"
            + result.stdout
            + "\nSTDERR\n------\n"
            + result.stderr
            + "\n"
        )
    if result.returncode:
        raise RuntimeError(
            f"SPM batch failed ({container.runtime} exit status {result.returncode}). "
            f"See {log_path}."
        )
