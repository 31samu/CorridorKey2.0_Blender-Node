# CorridorKey 2.0 with PyTorch

[Download the 0.5.8 test ZIP](corridorkey_mps_compositor-0.5.8.zip?raw=true) for Blender 5.3 or later on Apple Silicon or Windows x64. The extension runs the original CorridorKey 2.0 model and foundation weights through PyTorch MPS on Mac and experimental CUDA on Windows. The same model download covers all scene resolutions.

Use the node in the scene compositor or a scene compositor effect on either platform. MPS also supports top-level Sequencer strip compositor modifiers. The model keys green and blue screens and the node uses scene-linear EXR. Built-in despill targets green. You can supply an alpha hint for the first frame or every analyzed frame. The node offers automatic, single-frame, and four-frame Stage 1 windows.

[Setup and use](Setup.md) · [Backend source and validation](https://github.com/nikopueringer/CorridorKey2.0/pull/15) · [Performance measurements](../performance.md)

From my testing it seems this implementation, while fully featured and incomparibly less complex than the current MLX implementation, is drastically less performant, averaging 6.2s per frame instead of 1.8s for MLX, all else being equal.
