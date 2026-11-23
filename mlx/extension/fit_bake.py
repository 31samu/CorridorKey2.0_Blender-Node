# SPDX-License-Identifier: GPL-3.0-or-later
"""Fit an SDR bake to the model canvas using the backend's OpenCV."""

import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np


def fit_frames(folder, width, height, quarter_turns, hint=None):
    frames = sorted(folder.glob("*.png"))
    geometry = []
    for path, turns in zip(frames, quarter_turns, strict=True):
        geometry.append(fit_frame(path, width, height, turns))
    if hint is not None:
        if hint.is_dir():
            mattes = [hint / path.name for path in frames]
            hint_frames = zip(mattes, quarter_turns, geometry, strict=True)
        else:
            hint_frames = [(hint, quarter_turns[0], geometry[0])]
        for path, turns, source_geometry in hint_frames:
            if fit_frame(path, width, height, turns) != source_geometry:
                raise ValueError(f"Matte hint {path.name} has different bake dimensions from its source frame.")
    (folder / "geometry.json").write_text(json.dumps(geometry))


def fit_frame(path, width, height, turns):
    source = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if source is None:
        raise ValueError(f"Could not read baked frame {path.name}")
    if turns:
        source = np.rot90(source, turns)
    h, w = source.shape[:2]
    scale = min(width / w, height / h)
    size = max(1, round(w * scale)), max(1, round(h * scale))
    left, top = (width - size[0]) // 2, (height - size[1]) // 2
    if (w, h) != (width, height):
        interpolation = cv2.INTER_AREA if size[0] <= w and size[1] <= h else cv2.INTER_LINEAR
        fitted = cv2.resize(source, size, interpolation=interpolation)
        source = np.zeros((height, width, *source.shape[2:]), dtype=source.dtype)
        source[top:top + size[1], left:left + size[0]] = fitted
        write_frame(path, source)
    elif turns:
        write_frame(path, source)
    return [w, h, left, top, *size, turns]


def write_frame(path, pixels):
    temporary = path.with_suffix(".tmp.png")
    if not cv2.imwrite(str(temporary), pixels):
        raise OSError(f"Could not write frame {path.name}")
    temporary.replace(path)


def restore_frames(folder, geometry):
    for path, frame in zip(sorted(folder.glob("*.png")), geometry, strict=True):
        w, h, left, top, width, height, turns = frame
        source = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if source is None:
            raise ValueError(f"Could not read keyed frame {path.name}")
        if not turns and (w, h) == (source.shape[1], source.shape[0]) and (left, top, width, height) == (0, 0, w, h):
            continue
        pixels = source[top:top + height, left:left + width]
        if (width, height) != (w, h) and pixels.shape[2] == 4:
            # Resize premultiplied colour, then restore straight alpha for Blender.
            pixels = pixels.astype(np.float32) / 65535
            pixels[:, :, :3] *= pixels[:, :, 3:]
            pixels = cv2.resize(pixels, (w, h), interpolation=cv2.INTER_LINEAR)
            alpha = pixels[:, :, 3:]
            np.divide(pixels[:, :, :3], alpha, out=pixels[:, :, :3], where=alpha > 0)
            pixels = np.round(pixels.clip(0, 1) * 65535).astype(np.uint16)
        elif (width, height) != (w, h):
            pixels = cv2.resize(pixels, (w, h), interpolation=cv2.INTER_LINEAR)
        write_frame(path, np.rot90(pixels, -turns) if turns else pixels)


if __name__ == "__main__":
    if sys.argv[1] == "key":
        geometry = json.loads(Path(sys.argv[2]).read_text())
        subprocess.run(sys.argv[4:], check=True)
        for folder in json.loads(sys.argv[3]):
            restore_frames(Path(folder), geometry)
    else:
        fit_frames(
            Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), json.load(sys.stdin),
            Path(sys.argv[4]) if len(sys.argv) > 4 else None,
        )
