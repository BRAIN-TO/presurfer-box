"""SPM MATLAB batch-script generation helpers."""

import os
from pathlib import Path

MIN_THREADS = 8
MAX_THREADS = 16

__all__ = [
    "MAX_THREADS",
    "MIN_THREADS",
    "default_threads",
    "imcalc_job",
    "segmentation_job",
]


def default_threads() -> int:
    """Choose how many computational threads MATLAB should use.

    The MATLAB Runtime in the SPM container starts with a single thread, so
    SPM would otherwise use one core however many the machine has. This
    returns the number of available cores, but never fewer than
    ``MIN_THREADS`` and never more than ``MAX_THREADS``, because extra threads
    stop helping beyond a certain point.

    Returns:
        Thread count between 8 and 16 inclusive.
    """
    try:
        available = len(os.sched_getaffinity(0))
    except AttributeError:
        available = os.cpu_count() or MIN_THREADS
    return max(MIN_THREADS, min(MAX_THREADS, available))


def _thread_line(threads: int | None) -> str:
    """Return the MATLAB line that sets the thread count, or nothing.

    Args:
        threads: Number of computational threads, or ``None`` to leave the
            MATLAB default unchanged.

    Returns:
        A ``maxNumCompThreads`` statement ending in a newline, or an empty string.

    Raises:
        RuntimeError: If ``threads`` is less than one.
    """
    if threads is None:
        return ""
    if threads < 1:
        raise RuntimeError(f"Thread count must be at least 1, got: {threads}")
    return f"maxNumCompThreads({threads});\n"


def segmentation_job(
    input_file: str,
    output_dir: str,
    native: list[int],
    samp: int,
    threads: int | None = None,
) -> str:
    """Generate an SPM Unified Segmentation batch script.

    Args:
        input_file: Container path to the input NIfTI file.
        output_dir: Container path where SPM writes results.
        native: Six flags selecting native tissue-class outputs.
        samp: Segmentation sampling distance in millimetres.
        threads: Number of MATLAB computational threads, or ``None`` to keep
            the MATLAB default.

    Returns:
        Executable MATLAB batch-script source.
    """
    tissues = "\n".join(
        "matlabbatch{1}.spm.spatial.preproc.tissue(%d).tpm = {fullfile(spm('Dir'),'tpm','TPM.nii,%d')};\n"
        "matlabbatch{1}.spm.spatial.preproc.tissue(%d).ngaus = %d;\n"
        "matlabbatch{1}.spm.spatial.preproc.tissue(%d).native = [%d %d];\n"
        "matlabbatch{1}.spm.spatial.preproc.tissue(%d).warped = [0 0];"
        % (index, index, index, ngaus, index, native[index - 1], 0, index)
        for index, ngaus in enumerate((2, 2, 2, 3, 4, 2), 1)
    )
    return f"""{_thread_line(threads)}spm('defaults','FMRI');
spm_jobman('initcfg');
matlabbatch{{1}}.spm.spatial.preproc.channel.vols = {{'{input_file},1'}};
matlabbatch{{1}}.spm.spatial.preproc.channel.biasreg = 0.001;
matlabbatch{{1}}.spm.spatial.preproc.channel.biasfwhm = 30;
matlabbatch{{1}}.spm.spatial.preproc.channel.write = [1 1];
{tissues}
matlabbatch{{1}}.spm.spatial.preproc.warp.mrf = 1;
matlabbatch{{1}}.spm.spatial.preproc.warp.cleanup = 1;
matlabbatch{{1}}.spm.spatial.preproc.warp.reg = [0 0.001 0.5 0.05 0.2];
matlabbatch{{1}}.spm.spatial.preproc.warp.affreg = 'mni';
matlabbatch{{1}}.spm.spatial.preproc.warp.fwhm = 0;
matlabbatch{{1}}.spm.spatial.preproc.warp.samp = {samp};
matlabbatch{{1}}.spm.spatial.preproc.warp.write = [0 0];
matlabbatch{{1}}.spm.spatial.preproc.warp.vox = NaN;
matlabbatch{{1}}.spm.spatial.preproc.warp.bb = [NaN NaN NaN; NaN NaN NaN];
spm_jobman('run',matlabbatch);
save(fullfile('{output_dir}','{Path(input_file).stem}_presurfSegBatch.mat'),'matlabbatch');
"""


def imcalc_job(
    inputs: list[str],
    output: str,
    expression: str,
    batch_file: str,
    threads: int | None = None,
) -> str:
    """Generate an SPM Image Calculator batch script.

    Args:
        inputs: Container paths to input NIfTI files.
        output: Container path for the output NIfTI file.
        expression: SPM Image Calculator expression using ``i1``, ``i2``, etc.
        batch_file: Container path for the saved ``matlabbatch`` MAT file.
        threads: Number of MATLAB computational threads, or ``None`` to keep
            the MATLAB default.

    Returns:
        Executable MATLAB batch-script source.
    """
    quoted_inputs = "\n".join(f"    '{item},1'" for item in inputs)
    return f"""{_thread_line(threads)}spm('defaults','FMRI');
spm_jobman('initcfg');
matlabbatch{{1}}.spm.util.imcalc.input = {{
{quoted_inputs}
    }};
matlabbatch{{1}}.spm.util.imcalc.output = '{Path(output).name}';
matlabbatch{{1}}.spm.util.imcalc.outdir = {{'{Path(output).parent}'}};
matlabbatch{{1}}.spm.util.imcalc.expression = '{expression}';
matlabbatch{{1}}.spm.util.imcalc.var = struct('name', {{}}, 'value', {{}});
matlabbatch{{1}}.spm.util.imcalc.options.dmtx = 0;
matlabbatch{{1}}.spm.util.imcalc.options.mask = 0;
matlabbatch{{1}}.spm.util.imcalc.options.interp = -7;
matlabbatch{{1}}.spm.util.imcalc.options.dtype = 2;
spm_jobman('run',matlabbatch);
save('{batch_file}','matlabbatch');
"""
