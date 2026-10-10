"""Backward-compatible import and executable shim for presurfer-box."""

from presurfer import (
    IMAGE,
    SIF_IMAGE,
    presurf_biascorrect,
    presurf_mprageise,
    presurf_seg,
    presurf_stripmask,
)
from presurfer.command_line import main

__all__ = [
    "IMAGE",
    "SIF_IMAGE",
    "main",
    "presurf_biascorrect",
    "presurf_mprageise",
    "presurf_seg",
    "presurf_stripmask",
]


if __name__ == "__main__":
    main()
