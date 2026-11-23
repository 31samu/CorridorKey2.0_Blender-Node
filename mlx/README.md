# CorridorKey 2.0 with MLX

[Download MLX 0.4.1](corridorkey_mlx_compositor-0.4.1.zip?raw=true) for Blender 5.3 or later on Apple Silicon. Automatic setup requires macOS 26 or later. The add-on runs [Peter Teravskis's MLX port](https://github.com/peterteravskis/corridorkey-v2-mlx) locally.

Use the node in the scene compositor or in a Sequencer strip’s Compositor modifier. It supports green and blue despill, first-frame and animated alpha hints, and a garbage mask. It exposes the keyed image, matte, despilled and raw foreground, and edges.

On the recorded 720p Blender test, MLX took 1.83 seconds per frame and peaked at 3.93 GiB of backend memory on an M1 Pro with 16 GB of unified memory. [Benchmark details](../performance.md#standard-720p-blender-benchmark)

## Limitations

- **Fixed model sizes.** The add-on offers two downloadable mixed FP16 profiles, 1280 × 720 and 1536 × 1024. It fits footage into the selected canvas, which can soften higher-resolution footage. Native 1080p or 4K would require additional model profiles.
- **Single-frame Stage 1.** The Blender integration processes one frame per Stage 1 window. The alpha hint can still be sampled on every frame.
- **SDR image cache.** Input plates and keyed output use 16-bit PNG. For a scene-linear HDR bake and native-resolution Sequencer keying on Apple Silicon, use the [PyTorch edition](../pytorch/README.md).

[Setup and use](Setup.md) · [Performance measurements](../performance.md)
