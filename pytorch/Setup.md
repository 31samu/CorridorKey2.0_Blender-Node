# PyTorch setup

To build a test ZIP from source, run `blender --command extension build --source-dir pytorch/extension --output-dir <folder>` from the repository root. Use an existing folder outside the repository for the output.

1. In Blender 5.3 or later, choose **Preferences → Get Extensions → Install from Disk** and select the ZIP for this edition. Use Apple Silicon for MPS. For CUDA, use Windows x64, an NVIDIA RTX 30-series or newer GPU, a driver that supports CUDA 12.8, and at least 12 GB of free disk space. The current Windows build is for testing.
2. Enable **Allow Online Access** in Blender. In **Preferences → Add-ons**, expand the experimental CorridorKey PyTorch add-on and click **Set Up CorridorKey**. Setup installs a separate Python environment, PyTorch, FFmpeg, and the original CorridorKey and foundation models. The download is several GB. **Open Downloaded Runtime Folder** opens the runtime and setup logs.
3. In the scene compositor, choose **Add → Keying → CorridorKey2.0 (MPS)** on Mac or **CorridorKey2.0 (CUDA)** on Windows. Connect the footage, set the scene render resolution and percentage, choose the frame range, and click **Analyze**. The **Image** output is the despilled cutout. Under **More → Additional Outputs**, the node exposes **Matte**, **Raw Foreground**, and **Edges**.

**Time Awareness** defaults to **Automatic**. The runtime uses the working resolution, frame count, and GPU memory budget to pick the largest frame window it estimates will fit. **Single Frame** uses a window and step of 1. **Four Frames** uses a window of 4 and a step of 2. Stage 2 refines one frame per call. Choose **Clear Bake** to change the bake settings.

Under **More → Alpha Hint Settings**, connect a rough matte to **Alpha Hint**. Choose **First Frame** to sample it at **Start Frame**, or **All Frames** to sample it throughout the analysis range. **Alpha Hint Confidence** defaults to 0.95. Set it to zero to skip the hint during analysis.

The node bakes and loads scene-linear EXR in Linear Rec.709. The model keys both green and blue screens. **Despill Strength** under **More** adjusts green despill and defaults to 0.85. Lower it if the cutout loses green you want to keep. For blue spill, set it to zero and use a blue despill step in the compositor.

On MPS, you can also add the node in a top-level Sequencer strip compositor modifier. Movie and image strips are keyed at their source resolution. Blender applies the strip transforms and scene scaling during playback. Keep the frame range inside the selected strip.

Use **Node Defaults** in the add-on preferences to set Time Awareness, Larger Batches on MPS, Despill Strength, Alpha Hint Confidence, and Hint Frames for newly added nodes. Saved nodes keep their own settings. Frame ranges are filled from the connected footage or scene.

In **Advanced**, **EXR Precision** sets the format for newly baked cutout and raw foreground files. **16-bit Float** keeps caches smaller. **32-bit Float** retains more precision. **Delete Cache Files on Clear Bake** is in the main add-on preferences.

### MPS performance options

- Under the add-on's **Advanced** preferences, click **Build Native Attention** to compile and test the optional MPSGraph kernel. It requires macOS 15 or later and Apple's developer tools. A successful build enables **Use Native MPSGraph Attention**. You can turn it off to compare mattes with the standard PyTorch path. The runtime also uses the standard path if the optional library is unavailable or incompatible.
- **Larger Batches** is available with **Single Frame** and **Four Frames**. It increases some internal batch sizes without changing the model, resolution, or frame window. Larger batches can use more memory. If a shot runs out of memory, clear the option and analyze again. **Automatic** continues to choose its own batch sizes.

Use **Advanced → Custom Paths** to override the cache folder or select your own Python executable, CorridorKey checkout, and FFmpeg executable. To use native attention with an external MPS checkout, run that checkout's `scripts/build_mps_attention.py` in its Python environment, then enable **Use Native MPSGraph Attention**.

For setup failures, see `setup-*.log` or `native-attention-*.log` in the runtime folder. For bake or inference failures, see `analysis.log` in the bake cache.
