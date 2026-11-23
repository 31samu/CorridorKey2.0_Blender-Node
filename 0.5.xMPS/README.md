# CorridorKey 2.0 for Apple Silicon · MPS

[Download the experimental MPS extension](corridorkey_mps_compositor-0.5.1.zip?raw=true) for Blender 5.3 or later. This edition runs the original CorridorKey 2.0 model and foundation weights on the Apple GPU through PyTorch MPS. The same model download covers all scene resolutions.

Use the node in the scene compositor, a scene compositor effect, or a top-level Sequencer strip compositor modifier. It uses scene-linear EXR, green-screen despill, and an optional first-frame alpha hint. The node offers automatic, single-frame, and four-frame Stage 1 windows.

[Setup and use](Setup.md) · [Backend source and validation](https://github.com/nikopueringer/CorridorKey2.0/pull/15) · [Performance measurements](../performance.md)

From my testing it seems this implementation, while fully featured and incomparibly less complex than the current MLX implementation, is drastically less performant, averaging 6.2s per frame instead of 1.8s for MLX, all else being equal.