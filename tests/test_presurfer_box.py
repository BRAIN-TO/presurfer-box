"""Regression tests for workflow paths, scripts, and container execution."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from presurfer import command_line, container_runtime, output_paths
from presurfer.container_runtime import Container
from presurfer.spm_batch_scripts import (
    MAX_THREADS,
    MIN_THREADS,
    default_threads,
    imcalc_job,
    segmentation_job,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "batch_and_commands.json").read_text()
)
BASE = "/data/run/presurf_X/scan"
NATIVE = {
    "biascorrect": ([0] * 6, 3),
    "UNI": ([1, 1, 1, 0, 0, 0], 2),
    "INV2": ([0, 0, 1, 1, 1, 1], 2),
}


def test_nii_stem_rejects_non_nifti(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Expected a .nii"):
        output_paths.nii_stem(tmp_path / "scan.txt")


def test_utc_run_directory_adds_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, timezone: object = None) -> FixedDatetime:
            return cls(2026, 9, 8, 12, 34, 56, tzinfo=UTC)

    monkeypatch.setattr(output_paths, "datetime", FixedDatetime)
    first = output_paths.utc_run_directory(tmp_path)
    second = output_paths.utc_run_directory(tmp_path)
    temporary = output_paths.utc_run_directory(tmp_path, temporary=True)
    assert first.name == "260908T12:34:56_presurfer"
    assert second.name == "260908T12:34:56_presurfer-2"
    assert temporary.name == "tmp_260908T12:34:56_presurfer"


def test_run_spm_batch_captures_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "job.m"
    job.touch()
    log = tmp_path / "spm.log"
    monkeypatch.setattr(container_runtime, "container_command", lambda *_: ["spm"])
    monkeypatch.setattr(
        container_runtime.subprocess,
        "run",
        lambda *args, **kwargs: container_runtime.subprocess.CompletedProcess(
            args[0], 0, "normal output", "normal error"
        ),
    )
    monkeypatch.setattr(container_runtime, "_require_docker_image", lambda _: None)
    container_runtime.run_spm_batch(tmp_path, job, Container("docker", "image"), log)
    assert "normal output" in log.read_text()
    assert "normal error" in log.read_text()


def test_run_spm_batch_failure_points_to_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "job.m"
    job.touch()
    log = tmp_path / "spm.log"
    monkeypatch.setattr(container_runtime, "container_command", lambda *_: ["spm"])
    monkeypatch.setattr(
        container_runtime.subprocess,
        "run",
        lambda *args, **kwargs: container_runtime.subprocess.CompletedProcess(
            args[0], 7, "", "failure"
        ),
    )
    with pytest.raises(RuntimeError, match="apptainer exit status 7"):
        container_runtime.run_spm_batch(
            tmp_path, job, Container("apptainer", "image"), log
        )
    assert "failure" in log.read_text()


@pytest.mark.parametrize("kind", ["biascorrect", "UNI", "INV2"])
def test_segmentation_job_is_unchanged(kind: str) -> None:
    native, samp = NATIVE[kind]
    script = segmentation_job(
        f"/data/run/presurf_{kind}/scan.nii",
        f"/data/run/presurf_{kind}",
        native,
        samp,
    )
    assert script == FIXTURES[f"segmentation_{kind}"]


def test_imcalc_jobs_are_unchanged() -> None:
    brain = imcalc_job(
        [f"{BASE}_class{n}.nii" for n in (1, 2, 3)],
        f"{BASE}_brainmask.nii",
        "(i1+i2+i3)>0.3",
        f"{BASE}_presurfStripBatch.mat",
    )
    white = imcalc_job(
        [f"{BASE}_class2.nii"],
        f"{BASE}_WMmask.nii",
        "(i1)>0.5",
        f"{BASE}_presurfWMBatch.mat",
    )
    strip = imcalc_job(
        [f"{BASE}_class{n}.nii" for n in (3, 4, 5, 6)],
        f"{BASE}_stripmask.nii",
        "1-((i1+i2+i3+i4)>0.5)",
        f"{BASE}_presurfStripBatch.mat",
    )
    assert brain == FIXTURES["imcalc_brainmask"]
    assert white == FIXTURES["imcalc_wmmask"]
    assert strip == FIXTURES["imcalc_stripmask"]


def test_thread_line_leads_both_scripts() -> None:
    native, samp = NATIVE["UNI"]
    assert segmentation_job("/data/a.nii", "/data", native, samp, 12).startswith(
        "maxNumCompThreads(12);\nspm('defaults'"
    )
    assert imcalc_job(
        ["/data/a.nii"], "/data/b.nii", "i1", "/data/b.mat", 9
    ).startswith("maxNumCompThreads(9);\n")
    with pytest.raises(RuntimeError, match="at least 1"):
        segmentation_job("/data/a.nii", "/data", native, samp, 0)


@pytest.mark.parametrize(
    ("cores", "expected"),
    [(2, MIN_THREADS), (8, 8), (12, 12), (16, 16), (64, MAX_THREADS)],
)
def test_default_threads_is_clamped(
    cores: int, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "sched_getaffinity", lambda _: set(range(cores)))
    assert default_threads() == expected


def test_container_commands_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "job.m"
    job.touch()
    sif = tmp_path / "spm.sif"
    sif.touch()
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    docker = container_runtime.container_command(
        tmp_path, job, Container("docker", "img:tag")
    )
    monkeypatch.setattr(
        shutil, "which", lambda n: "/usr/bin/apptainer" if n == "apptainer" else None
    )
    apptainer = container_runtime.container_command(
        tmp_path, job, Container("apptainer", str(sif))
    )
    mount = str(tmp_path.resolve())
    assert docker == [p.replace("/tmp/mnt", mount) for p in FIXTURES["cmd_docker"]]
    assert apptainer == [
        p.replace("/tmp/mnt/spm.sif", str(sif)).replace("/tmp/mnt", mount)
        for p in FIXTURES["cmd_apptainer"]
    ]


def test_apptainer_must_be_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "job.m"
    job.touch()
    sif = tmp_path / "spm.sif"
    sif.touch()
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Apptainer was not found"):
        container_runtime.container_command(
            tmp_path, job, Container("apptainer", str(sif))
        )


def test_apptainer_image_must_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = tmp_path / "job.m"
    job.touch()
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/apptainer")
    with pytest.raises(RuntimeError, match="Pull it first: apptainer pull"):
        container_runtime.container_command(
            tmp_path, job, Container("apptainer", str(tmp_path / "missing.sif"))
        )


def test_unsupported_runtime_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="Unsupported runtime"):
        Container("singularity", "image")  # type: ignore[arg-type]


def test_engine_option_validation(tmp_path: Path) -> None:
    sif = tmp_path / "spm.sif"
    sif.touch()
    runner = CliRunner()
    needs_sif = runner.invoke(command_line.main, ["--engine", "apptainer", "--check"])
    assert needs_sif.exit_code != 0
    assert "needs --sif" in needs_sif.output
    docker_sif = runner.invoke(
        command_line.main, ["--engine", "docker", "--sif", str(sif), "--check"]
    )
    assert docker_sif.exit_code != 0
    assert "cannot be used with --engine docker" in docker_sif.output
