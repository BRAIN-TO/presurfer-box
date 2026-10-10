"""Backward-compatible import and executable shim for presurfer-box."""

from presurfer import (
    IMAGE,
    SIF_IMAGE,
    spm_biascorrect,
    spm_mprageise,
    spm_seg,
    spm_stripmask,
)
from presurfer.command_line import main

__all__ = [
    "IMAGE",
    "SIF_IMAGE",
    "main",
    "spm_biascorrect",
    "spm_mprageise",
    "spm_seg",
    "spm_stripmask",
]


if __name__ == "__main__":
    main()
