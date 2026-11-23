# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the upstream CorridorKey 2.0 CLI in a user's MPS environment."""

import json
import os
from pathlib import Path
import re
import shutil

from .sequences import KEYED_FRAMES, RAW_FOREGROUND, OutputSequence

LINEAR_COLOR_SPACE = "Linear Rec.709"
PROGRESS_LINE = re.compile(rb"^ +window (\d+)/(\d+) \[", re.MULTILINE)


def validate_runtime(python, checkout, ffmpeg):
    if not os.access(python, os.X_OK):
        raise ValueError("Choose the MPS environment's Python executable in the add-on preferences.")
    if not (checkout / "infer.py").is_file() or not (checkout / "corridorkey/runtime.py").is_file():
        raise ValueError("Choose the upstream CorridorKey 2.0 folder containing infer.py.")
    for stem in ("corridorkey_v2", "foundation_stats"):
        if not any((checkout / "weights" / f"{stem}.{suffix}").is_file() for suffix in ("safetensors", "pt")):
            raise ValueError("Run scripts/download_weights.py in the upstream CorridorKey 2.0 folder first.")
    if not shutil.which(str(ffmpeg)):
        raise ValueError("Install FFmpeg on PATH or choose the FFmpeg executable in the add-on preferences.")


def analysis_command(python, checkout, ffmpeg, config, output, fps, temporal, despill):
    command = [
        str(python), "-E", "-s", "-X", "utf8", "-u", str(checkout / "infer.py"),
        "--input", config["destination"], "--output_dir", str(output),
        "--output_format", "exr", "--outputs", "cutout", "fg",
        "--despill_strength", str(despill),
        "--frame_dir_linear", "--frame_dir_fps", str(fps),
        "--ffmpeg_bin", str(ffmpeg), "--temp_dir", str(output.parent / "scratch"),
    ]
    if temporal != "AUTO":
        frames = int(temporal)
        # A manual window bypasses upstream's automatic Metal batch limits.
        command.extend((
            "--hann_chunk", str(frames), "--hann_stride", str(max(1, frames // 2)), "--low_vram",
            "--low_vram_foundation_chunk", "1",
            "--low_vram_full_attn_query_chunk_tokens", "128",
            "--low_vram_swin_window_batch", "1",
            "--low_vram_mlp_chunk_tokens", "4096",
        ))
    if hint := config.get("hint"):
        command.extend(("--hint_first_frame", hint["path"]))
    if config["context"] == "strip":
        geometry = Path(config["destination"]) / "geometry.json"
        folders = [str(sequence.folder) for sequence in output_sequences(output)]
        return [
            str(python), "-I", str(Path(__file__).with_name("fit_bake.py")), "key",
            str(geometry), json.dumps(folders), *command,
        ]
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
