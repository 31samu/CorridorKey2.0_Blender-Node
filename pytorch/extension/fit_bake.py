# SPDX-License-Identifier: GPL-3.0-or-later
"""Rotate and pad scene-linear strip frames without resampling their pixels."""

import json
import os
from pathlib import Path
import subprocess
import sys

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import cv2
import numpy as np


def fit_frames(folder, width, height, quarter_turns, hint=None):
    frames = sorted(folder.glob("*.exr"))
    sizes = [(height, width) if turns % 2 else (width, height) for turns in quarter_turns]
    canvas_width = max(w for w, _ in sizes)
    canvas_height = max(h for _, h in sizes)
    geometry = [
        [w, h, (canvas_width - w) // 2, (canvas_height - h) // 2, turns]
        for (w, h), turns in zip(sizes, quarter_turns, strict=True)
    ]
    for path, frame in zip(frames, geometry, strict=True):
        fit_frame(path, canvas_width, canvas_height, frame)
    if hint is not None:
        if hint.is_dir():
            mattes = [hint / path.with_suffix(".png").name for path in frames]
            hint_frames = zip(mattes, geometry, strict=True)
        else:
            hint_frames = [(hint, geometry[0])]
        for path, frame in hint_frames:
            fit_frame(path, canvas_width, canvas_height, frame)
    (folder / "geometry.json").write_text(json.dumps(geometry))


def fit_frame(path, width, height, frame):
    w, h, left, top, turns = frame
    if not turns and (w, h) == (width, height):
        return
    source = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if source is None:
        raise ValueError(f"Could not read baked frame {path.name}")
    if turns:
        source = np.rot90(source, turns)
    if source.shape[:2] != (h, w):
        raise ValueError(f"Baked frame {path.name} does not match the expected dimensions.")
    if (w, h) != (width, height):
        canvas = np.zeros((height, width, *source.shape[2:]), dtype=source.dtype)
        canvas[top:top + h, left:left + w] = source
        source = canvas
    write_frame(path, source)


def write_frame(path, pixels, params=()):
    temporary = path.with_suffix(f".tmp{path.suffix}")
    if not cv2.imwrite(str(temporary), pixels, params):
        raise OSError(f"Could not write frame {path.name}")
    temporary.replace(path)


def restore_frames(folder, geometry, exr_dtype):
    exr_type = {"half": cv2.IMWRITE_EXR_TYPE_HALF, "float": cv2.IMWRITE_EXR_TYPE_FLOAT}[exr_dtype]
    canvas_width = max(w for w, _, _, _, _ in geometry)
    canvas_height = max(h for _, h, _, _, _ in geometry)
    for path, frame in zip(sorted(folder.glob("*.exr")), geometry, strict=True):
        w, h, left, top, turns = frame
        if not turns and (w, h) == (canvas_width, canvas_height):
            continue
        source = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if source is None:
            raise ValueError(f"Could not read keyed frame {path.name}")
        if source.shape[:2] != (canvas_height, canvas_width):
            raise ValueError(f"Keyed frame {path.name} does not match the model canvas.")
        pixels = source[top:top + h, left:left + w]
        write_frame(path, np.rot90(pixels, -turns) if turns else pixels, (cv2.IMWRITE_EXR_TYPE, exr_type))


if __name__ == "__main__":
    if sys.argv[1] == "key":
        geometry = json.loads(Path(sys.argv[2]).read_text())
        subprocess.run(sys.argv[5:], check=True)
        for folder in json.loads(sys.argv[3]):
            restore_frames(Path(folder), geometry, sys.argv[4])
    else:
        fit_frames(
            Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), json.load(sys.stdin),
            Path(sys.argv[4]) if len(sys.argv) > 4 else None,
        )
