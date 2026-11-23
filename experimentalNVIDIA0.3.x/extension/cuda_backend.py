# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the upstream CorridorKey 2.0 CLI in a user's CUDA environment."""

import re
import shutil

from .sequences import KEYED_FRAMES, RAW_FOREGROUND, OutputSequence

LINEAR_COLOR_SPACE = "Linear Rec.709"
PROGRESS_LINE = re.compile(rb"^ +window (\d+)/(\d+) \[", re.MULTILINE)


def validate_runtime(python, checkout, ffmpeg):
    if not python.is_file():
        raise ValueError("Choose the CUDA environment's python.exe in the add-on preferences.")
    if not (checkout / "infer.py").is_file() or not (checkout / "corridorkey/runtime.py").is_file():
        raise ValueError("Choose the upstream CorridorKey 2.0 folder containing infer.py.")
    for stem in ("corridorkey_v2", "foundation_stats"):
        if not any((checkout / "weights" / f"{stem}.{suffix}").is_file() for suffix in ("safetensors", "pt")):
            raise ValueError("Run scripts/download_weights.py in the upstream CorridorKey 2.0 folder first.")
    if not shutil.which(str(ffmpeg)):
        raise ValueError("Install FFmpeg on PATH or choose ffmpeg.exe in the add-on preferences.")


def analysis_command(python, checkout, ffmpeg, config, output, fps):
    command = [
        str(python), "-E", "-s", "-X", "utf8", "-u", str(checkout / "infer.py"),
        "--input", config["destination"], "--output_dir", str(output),
        "--output_format", "exr", "--outputs", "cutout", "fg",
        "--frame_dir_linear", "--frame_dir_fps", str(fps),
        "--ffmpeg_bin", str(ffmpeg), "--temp_dir", str(output.parent / "scratch"),
    ]
    if hint := config.get("hint"):
        command.extend(("--hint_first_frame", hint["path"]))
    return command


def output_sequences(output):
    return (
        OutputSequence(KEYED_FRAMES, output / "baked-input_cutout_exr", ".exr", "STRAIGHT", LINEAR_COLOR_SPACE),
        OutputSequence(RAW_FOREGROUND, output / "baked-input_fg_exr", ".exr", "NONE", LINEAR_COLOR_SPACE),
    )


def read_progress(data):
    matches = PROGRESS_LINE.findall(data)
    if matches:
        current, total = matches[-1]
        return 2, "Analyzing windows", int(current), int(total)
