# MPS setup

1. In Blender 5.3 or later on Apple Silicon, choose **Preferences → Get Extensions → Install from Disk** and select the MPS ZIP. The MPS build has a separate extension ID and can sit alongside the MLX build.
2. Enable **Allow Online Access** in Blender. Under **Preferences → Add-ons → CorridorKey MPS Node (Experimental)**, click **Set Up CorridorKey**. Setup installs a separate Python environment, PyTorch, FFmpeg, and the original CorridorKey and foundation models. The download is several GB. **Open Downloaded Runtime Folder** opens the runtime and setup logs.
3. In the scene compositor or a top-level Sequencer strip compositor modifier, choose **Add → Keying → CorridorKey2.0 (MPS)** and connect the footage. Set the scene render resolution and percentage to the working size. Choose the frame range and click **Analyze**. The **Image** output is the despilled cutout. Under **More**, the node exposes **Matte**, **Raw Foreground**, **Edges**, and the optional first-frame **Alpha Hint**.

**Time Awareness** defaults to **Automatic**, which lets the runtime choose based on available memory. **Single Frame** uses a window and step of 1. **Four Frames** uses a window of 4 and a step of 2. Stage 2 refines one frame per call. Choose **Clear Bake** to change the bake settings.

The node bakes and loads scene-linear EXR in Linear Rec.709. For a Sequencer strip, it fits the image to the scene working size and restores the strip geometry for playback. The frame range must be inside the selected strip. The model uses green-channel despill, with a node slider defaulting to 0.5.

If you already have the [MPS backend](https://github.com/nikopueringer/CorridorKey2.0/pull/15) installed, set its Python executable and checkout folder under **Advanced**. Set the FFmpeg executable there if Blender cannot find it on PATH. The managed installer uses the backend's bounded PyTorch path. A manually configured checkout can use the upstream optional MPSGraph attention build.

For setup failures, see `setup-*.log` in the runtime folder. For bake or inference failures, see `analysis.log` in the bake cache.
