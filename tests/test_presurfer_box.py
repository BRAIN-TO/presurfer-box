"""Regression tests for workflow paths, scripts, and container execution."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import nibabel as nib
import numpy as np
import pytest
from click.testing import CliRunner

from presurfer import (
    command_line,
    container_runtime,
    output_paths,
    presurfer_workflows,
    spm_runner,
)
from presurfer.container_runtime import Container
from presurfer.spm_batch_scripts import (
    MAX_THREADS,
    MIN_THREADS,
    default_threads,
    imcalc_job,
    segmentation_job,
)
from presurfer.spm_runner import ContainerRunner, SegmentationFiles

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "batch_and_commands.json").read_text()
)
BASE = "/data/run/presurf_X/scan"
SEGMENTATIONS = 2
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
    container = Container("docker", "image")
    container_runtime.run_spm_batch(tmp_path, job, container, log, 12)
    container_runtime.run_spm_batch(tmp_path, job, container, log)
    text = log.read_text()
    assert "normal output" in text
    assert "normal error" in text
    assert "Container: docker image" in text
    assert "MATLAB threads: 12" in text
    assert "MATLAB threads: MATLAB default" in text
    assert text.count("SPM batch: job.m") > 1


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


def test_both_command_names_are_declared() -> None:
    import tomllib

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())[
        "project"
    ]
    assert project["scripts"] == {
        "presurfer": "presurfer.command_line:main",
        "presurfer-box": "presurfer.command_line:main",
    }


def _load(path: Path) -> np.ndarray:
    image = cast("nib.Nifti1Image", nib.load(str(path)))
    return np.asarray(image.dataobj)


def _save(path: Path, data: np.ndarray) -> None:
    nib.save(nib.Nifti1Image(data.astype(np.float32), np.eye(4)), str(path))


class FakeRunner:
    """An in-memory stand-in for SPM that writes small images."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def segment(
        self,
        image: Path,
        native: list[int],
        samp: int,
        keep_classes: tuple[int, ...],
    ) -> SegmentationFiles:
        self.calls.append("segment")
        out = image.parent
        data = _load(image)
        stem = output_paths.nii_stem(image)
        biascorrected = out / f"{stem}_biascorrected.nii"
        biasfield = out / f"{stem}_biasfield.nii"
        _save(biascorrected, data * 2.0)
        _save(biasfield, np.ones_like(data))
        classes = {}
        for number in keep_classes:
            classes[number] = out / f"{stem}_class{number}.nii"
            _save(classes[number], np.full_like(data, 0.5))
        return SegmentationFiles(biascorrected, biasfield, classes)

    def image_calc(
        self,
        inputs: list[Path],
        output: Path,
        expression: str,
        batch_file: Path,
    ) -> Path:
        self.calls.append("image_calc")
        _save(output, np.ones((4, 4, 4)))
        return output


def test_recon_prep_runs_two_segmentations(tmp_path: Path) -> None:
    inv2 = np.arange(64, dtype=np.float64).reshape(4, 4, 4) + 1
    uni = np.full((4, 4, 4), 3.0)
    _save(tmp_path / "inv2.nii.gz", inv2)
    _save(tmp_path / "uni.nii.gz", uni)
    runner = FakeRunner()
    run_dir = presurfer_workflows.recon_prep(
        tmp_path / "inv2.nii.gz",
        tmp_path / "uni.nii.gz",
        runner,
        reporter=lambda _: None,
    )
    assert runner.calls.count("segment") == SEGMENTATIONS
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "presurf_INV2",
        "presurf_MPRAGEise",
        "presurf_UNI",
    ]
    assert not list(tmp_path.glob("tmp_*"))
    mprageised = run_dir / "presurf_MPRAGEise" / "uni_MPRAGEised.nii"
    scaled = inv2 * 2.0
    expected = uni * (scaled - scaled.min()) / (scaled.max() - scaled.min())
    assert np.allclose(_load(mprageised), expected)
    assert (run_dir / "presurf_UNI" / "uni_MPRAGEised.nii").is_file()
    assert (run_dir / "presurf_UNI" / "uni_MPRAGEised_brainmask.nii").is_file()
    assert (run_dir / "presurf_INV2" / "inv2_stripmask.nii").is_file()


def test_recon_prep_rejects_mismatched_grids_before_running_spm(
    tmp_path: Path,
) -> None:
    _save(tmp_path / "inv2.nii", np.ones((4, 4, 4)))
    _save(tmp_path / "uni.nii", np.ones((5, 4, 4)))
    runner = FakeRunner()
    with pytest.raises(RuntimeError, match="matching dimensions"):
        presurfer_workflows.recon_prep(
            tmp_path / "inv2.nii", tmp_path / "uni.nii", runner
        )
    assert runner.calls == []
    assert not list(tmp_path.glob("*_presurfer"))


def test_standalone_mprageise_still_cleans_up_its_temporary_stage(
    tmp_path: Path,
) -> None:
    inv2 = np.arange(64, dtype=np.float64).reshape(4, 4, 4) + 1
    _save(tmp_path / "inv2.nii", inv2)
    _save(tmp_path / "uni.nii", np.full((4, 4, 4), 3.0))
    runner = FakeRunner()
    output = presurfer_workflows.mprageise(
        tmp_path / "inv2.nii",
        tmp_path / "uni.nii",
        runner,
        reporter=lambda _: None,
    )
    assert runner.calls == ["segment"]
    assert output.name == "uni_MPRAGEised.nii"
    assert output.parent.name == "presurf_MPRAGEise"
    assert not list(tmp_path.glob("tmp_*"))


def test_stripmask_workflow_names_its_outputs(tmp_path: Path) -> None:
    _save(tmp_path / "inv2.nii", np.ones((4, 4, 4)))
    out = presurfer_workflows.run_segmentation(
        tmp_path / "inv2.nii", "INV2", FakeRunner(), reporter=lambda _: None
    )
    assert out.name == "presurf_INV2"
    assert sorted(p.name for p in out.iterdir() if p.suffix == ".nii") == [
        "inv2.nii",
        "inv2_biascorrected.nii",
        "inv2_biasfield.nii",
        "inv2_class3.nii",
        "inv2_class4.nii",
        "inv2_class5.nii",
        "inv2_class6.nii",
        "inv2_stripmask.nii",
    ]


def _spm_like_subprocess(calls: list[Path]) -> object:
    """Stand in for the container: write what SPM would write, host side."""

    def run(
        mount_root: Path,
        job: Path,
        container: Container,
        log: Path,
        threads: int | None = None,
    ) -> None:
        calls.append(job)
        assert job.is_file()
        text = job.read_text()
        assert text.startswith(f"maxNumCompThreads({threads});")
        log.write_text(f"ran {job.name}\n")
        if "preproc" in text:
            match = re.search(r"vols = \{'/data/(.*),1'\}", text)
            assert match
            source = mount_root / match.group(1)
            data = _load(source)
            out, stem = source.parent, source.stem
            _save(out / f"m{stem}.nii", data)
            _save(out / f"BiasField_{stem}.nii", data)
            for number in (3, 4):
                _save(out / f"c{number}{stem}.nii", data)
            (out / f"{stem}_seg8.mat").write_text("seg8")
        else:
            match = re.search(r"output = '(.*)';", text)
            assert match
            _save(job.parent / match.group(1), np.ones((4, 4, 4)))

    return run


def test_container_runner_names_outputs_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "260908T12:34:56_presurfer"
    out = run_dir / "presurf_INV2"
    out.mkdir(parents=True)
    _save(out / "scan.nii", np.ones((4, 4, 4)))
    jobs: list[Path] = []
    monkeypatch.setattr(spm_runner, "run_spm_batch", _spm_like_subprocess(jobs))
    runner = ContainerRunner(Container("docker", "image"), threads=5)
    files = runner.segment(out / "scan.nii", [0, 0, 1, 1, 1, 1], 2, (3, 4))
    assert files.biascorrected == out / "scan_biascorrected.nii"
    assert files.biasfield == out / "scan_biasfield.nii"
    assert sorted(files.classes) == [3, 4]
    assert files.classes[3] == out / "scan_class3.nii"
    result = runner.image_calc(
        [files.classes[3], files.classes[4]],
        out / "scan_mask.nii",
        "i1+i2",
        out / "scan_batch.mat",
    )
    assert result.is_file()
    assert [job.name for job in jobs] == [
        ".presurfer_segmentation.m",
        ".presurfer_imcalc.m",
    ]
    assert not any(job.exists() for job in jobs)
    assert not list(out.glob("c[0-9]*")) and not (out / "scan_seg8.mat").exists()
    assert not (out / "mscan.nii").exists()


def test_container_runner_defaults_to_clamped_thread_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "sched_getaffinity", lambda _: set(range(64)))
    assert ContainerRunner(Container("docker", "image")).threads == MAX_THREADS
    assert ContainerRunner(Container("docker", "image"), 1).threads == 1


def test_recon_prep_command_is_registered() -> None:
    result = CliRunner().invoke(command_line.main, ["recon-prep", "--help"])
    assert result.exit_code == 0
    assert "INV2_FILE" in result.output
