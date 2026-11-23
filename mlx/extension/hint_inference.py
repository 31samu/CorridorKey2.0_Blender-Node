# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the pinned MLX CLI with configurable hint confidence."""

import sys

from corridorkey_mlx import cli, pipeline


def main(confidence, arguments):
    run = pipeline.run

    def run_with_hint(model, *args, **kwargs):
        def set_hint_confidence(_stage, inputs):
            # With single-frame windows, positive quality marks a supplied hint.
            # For a first-frame hint, leave any later windows to the backend.
            if kwargs.get("hint_source") is None:
                hook.remove()
            *features, quality = inputs
            quality = quality.masked_fill(quality > 0, confidence).bfloat16().float()
            return (*features, quality)

        hook = model.stage1.register_forward_pre_hook(set_hint_confidence)
        try:
            return run(model, *args, **kwargs)
        finally:
            hook.remove()

    pipeline.run = run_with_hint
    try:
        return cli.main(arguments)
    finally:
        pipeline.run = run


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]), sys.argv[2:]))
