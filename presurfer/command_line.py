"""Click command-line interface for presurfer."""

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import click
from rich.console import Console

from presurfer.container_runtime import IMAGE, Container, check_container
from presurfer.presurfer_workflows import (
    presurf_biascorrect,
    presurf_mprageise,
    presurf_recon_prep,
    presurf_seg,
    presurf_stripmask,
)

CONSOLE = Console()

__all__ = ["main"]


def _invoke_workflow(
    ctx: click.Context, operation: Callable[..., Path], *args: Path
) -> Path:
    """Run a public workflow and translate its errors for the Click CLI.

    Args:
        ctx: Click context containing runtime configuration.
        operation: Public workflow function to call.
        *args: NIfTI input paths accepted by the workflow.

    Raises:
        click.ClickException: If the workflow fails before producing output.

    Returns:
        The path returned by the workflow.
    """
    try:
        started = time.monotonic()
        output = operation(*args, **ctx.obj)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise click.ClickException(str(error)) from error
    CONSOLE.print(f"[green]Complete[/green] in {time.monotonic() - started:.1f}s")
    CONSOLE.print(str(output))
    return output


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.option("--image", help="Docker image tag. Docker is the default runtime.")
@click.option(
    "--sif",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Apptainer SIF file. Implies --engine apptainer.",
)
@click.option(
    "--engine",
    type=click.Choice(["docker", "apptainer"]),
    help="Container engine. Defaults to docker, or to apptainer with --sif.",
)
@click.option(
    "--threads",
    type=click.IntRange(min=1),
    help="MATLAB threads for SPM. Default: available cores, between 8 and 16.",
)
@click.option(
    "--check",
    "check_",
    is_flag=True,
    help="Check the selected SPM container and print its version.",
)
@click.pass_context
def main(
    ctx: click.Context,
    *,
    image: str | None,
    sif: Path | None,
    engine: str | None,
    threads: int | None,
    check_: bool,
) -> None:
    """Run MATLAB-free presurfer workflows through SPM Standalone.

    \f
    Args:
        ctx: Click context used to pass selected runtime configuration.
        image: Optional Docker image tag.
        sif: Optional local Apptainer SIF path.
        engine: Optional container engine: ``docker`` or ``apptainer``.
        threads: Optional MATLAB thread count.
        check_: Whether to check the selected container and exit.

    Raises:
        click.UsageError: If the engine, image, and SIF options conflict.
    """
    if image and sif:
        raise click.UsageError("Use either --image or --sif, not both.")
    if engine == "docker" and sif:
        raise click.UsageError("--sif cannot be used with --engine docker.")
    if engine == "apptainer" and not sif:
        raise click.UsageError("--engine apptainer needs --sif.")
    ctx.ensure_object(dict)
    ctx.obj["image"] = str(sif) if sif else (image or IMAGE)
    ctx.obj["runtime"] = engine or ("apptainer" if sif else "docker")
    ctx.obj["threads"] = threads
    if check_:
        try:
            container = Container(ctx.obj["runtime"], ctx.obj["image"])
            click.echo(check_container(container))
        except RuntimeError as error:
            raise click.ClickException(str(error)) from error
        ctx.exit()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command(name="biascorrect")
@click.argument(
    "input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.pass_context
def cmd_biascorrect(ctx: click.Context, input_file: Path) -> None:
    """Create a bias-corrected image from INPUT_FILE."""
    _invoke_workflow(ctx, presurf_biascorrect, input_file)


@main.command(name="MPRAGEise")
@click.argument(
    "inv2_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.argument(
    "uni_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.pass_context
def cmd_mprageise(ctx: click.Context, inv2_file: Path, uni_file: Path) -> None:
    """Create an MPRAGEised UNI image from INV2_FILE and UNI_FILE."""
    _invoke_workflow(ctx, presurf_mprageise, inv2_file, uni_file)


@main.command(name="recon-prep")
@click.argument(
    "inv2_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.argument(
    "uni_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.pass_context
def cmd_recon_prep(ctx: click.Context, inv2_file: Path, uni_file: Path) -> None:
    """Prepare INV2_FILE and UNI_FILE for FreeSurfer in one run.

    Creates the strip mask from INV2, an MPRAGEised UNI that reuses the INV2
    bias correction, and the brain and white-matter masks from the MPRAGEised
    UNI. This needs two SPM segmentations instead of three.
    """
    run_dir = _invoke_workflow(ctx, presurf_recon_prep, inv2_file, uni_file)
    for suffix in ("_MPRAGEised", "_stripmask", "_brainmask", "_WMmask"):
        for path in sorted(run_dir.glob(f"presurf_*/*{suffix}.nii")):
            CONSOLE.print(f"  {path.relative_to(run_dir)}")


@main.command(name="stripmask")
@click.argument(
    "input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.pass_context
def cmd_stripmask(ctx: click.Context, input_file: Path) -> None:
    """Create an INV2-derived strip mask from INPUT_FILE."""
    _invoke_workflow(ctx, presurf_stripmask, input_file)


@main.command(name="brainmask")
@click.argument(
    "input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.pass_context
def cmd_brainmask(ctx: click.Context, input_file: Path) -> None:
    """Create UNI tissue classes, brain mask, and WM mask from INPUT_FILE."""
    _invoke_workflow(ctx, presurf_seg, input_file)


if __name__ == "__main__":
    main()
