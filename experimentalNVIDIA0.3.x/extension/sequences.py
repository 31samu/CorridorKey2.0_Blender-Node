# SPDX-License-Identifier: GPL-3.0-or-later
"""The image sequences a backend hands back to the compositor."""

from dataclasses import dataclass
from pathlib import Path
import re

KEYED_FRAMES = "Keyed Frames"
DESPILLED_FOREGROUND = "Despilled Foreground"
RAW_FOREGROUND = "Raw Foreground"
FOREGROUND_OUTPUTS = (DESPILLED_FOREGROUND, RAW_FOREGROUND)
SEQUENCE_NODES = (KEYED_FRAMES, *FOREGROUND_OUTPUTS)


@dataclass(frozen=True)
class OutputSequence:
    node_name: str
    folder: Path
    extension: str
    alpha_mode: str
    color_space: str | None = None

    def locate(self, frame_count):
        frames = sorted(self.folder.rglob(f"*{self.extension}"))
        if len(frames) != frame_count:
            raise ValueError(
                f"{self.node_name}: expected {frame_count} output frames, found {len(frames)}."
            )
        parts = [re.fullmatch(r"(.*?)([0-9]+)", frame.stem) for frame in frames]
        first = parts[0]
        if not first or any(
            part is None
            or frame.parent != frames[0].parent
            or part[1] != first[1]
            or len(part[2]) != len(first[2])
            or int(part[2]) != int(first[2]) + index
            for index, (frame, part) in enumerate(zip(frames, parts))
        ):
            raise ValueError(f"{self.node_name}: output frames are not one contiguous sequence.")
        return frames[0], int(first[2]) - 1
