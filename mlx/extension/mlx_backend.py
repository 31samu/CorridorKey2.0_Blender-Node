# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan inference jobs for the CorridorKey MLX CLI."""

import json
import os
from pathlib import Path
import re

from .sequences import DESPILLED_FOREGROUND, KEYED_FRAMES, RAW_FOREGROUND, OutputSequence

PROFILE_ITEMS = (
    ("720", "1280 × 720", "Use the 768 × 1280 FP16 profile"),
    ("1024", "1536 × 1024", "Use the optional 1024 × 1536 FP16 profile"),
)
PROFILE_SIZES = {"720": (768, 1280, 720), "1024": (1024, 1536, 1024)}
LARGE_MODEL_FILES = json.loads(Path(__file__).with_name("model-1536x1024-files.json").read_text())
SCREEN_ITEMS = (("green", "Green", ""), ("blue", "Blue", ""))
OUTPUTS = (
    ("cutout", KEYED_FRAMES, "STRAIGHT"),
    ("fg", DESPILLED_FOREGROUND, "NONE"),
    ("raw_fg", RAW_FOREGROUND, "NONE"),
)
PROGRESS_LINE = re.compile(rb"^(Features|Export) (\d+)/(\d+)$", re.MULTILINE)
PROGRESS_STAGES = {b"Features": (2, "Analyzing source"), b"Export": (3, "Keying frames")}


def bake_size(profile):
    _, width, height = PROFILE_SIZES[profile]
    return width, height


def large_model_ready(models):
    return all((models / name).is_file() for name in LARGE_MODEL_FILES)


def validate_runtime(executable, models, profile):
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Choose the executable corridorkey-mlx in the backend environment.")
    height, width, _ = PROFILE_SIZES[profile]
    profile_folder = f"{height}x{width}-t1"
    if profile == "1024" and not large_model_ready(models):
        raise ValueError("Download the 1536 × 1024 model in the extension preferences first.")
    if not (models / "fp16" / profile_folder / "stats.json").is_file():
        raise ValueError(f"FP16 profile {profile_folder} is missing from the model folder.")


def geometry_python(executable):
    python = executable.with_name("python")
    if not os.access(python, os.X_OK):
        raise ValueError("The MLX executable must be in the backend environment's bin folder alongside Python.")
    return python


def analysis_command(executable, models, config, destination, screen, profile):
    height, width, _ = PROFILE_SIZES[profile]
    source = Path(config["destination"])
    command = [
        str(executable), "--model-root", str(models),
        "--input", str(source), "--output-dir", str(destination),
        "--height", str(height), "--width", str(width),
        "--precision", "fp16", "--screen", screen,
        "--despill-strength", str(config["despill_strength"]),
        "--hann-chunk", "1", "--hann-stride", "1",
        "--image-sequence", "--outputs", *(folder for folder, _, _ in OUTPUTS),
    ]
    if hint := config.get("hint"):
        hint_option = "--hint-video" if hint["every_frame"] else "--hint-first-frame"
        command = [
            str(geometry_python(executable)), "-I", str(Path(__file__).with_name("hint_inference.py")),
            str(hint["confidence"]), *command[1:], hint_option, hint["path"],
        ]
    if config["context"] == "strip":
        output_folders = [str(destination / folder) for folder, _, _ in OUTPUTS]
        return [
            config["python"], "-I", str(Path(__file__).with_name("fit_bake.py")), "key",
            str(source / "geometry.json"), json.dumps(output_folders), *command,
        ]
    return command


def output_sequences(destination):
    return tuple(
        OutputSequence(name, destination / folder, ".png", alpha_mode)
        for folder, name, alpha_mode in OUTPUTS
    )


def read_progress(data):
    matches = PROGRESS_LINE.findall(data)
    if matches:
        phase, current, total = matches[-1]
        step, label = PROGRESS_STAGES[phase]
        return step, label, int(current), int(total)
