# MLX setup

To build a test ZIP from source, run `blender --command extension build --source-dir mlx/extension --output-dir <folder>` from the repository root. Use an existing folder outside the repository for the output.

1. In Blender 5.3 or later on Apple Silicon, choose **Preferences → Get Extensions → Install from Disk** and select the [MLX ZIP](corridorkey_mlx_compositor-0.4.1.zip?raw=true).
2. Enable **Allow Online Access** in Blender. Under **Preferences → Add-ons**, expand **CorridorKey MLX Node** and click **Set Up CorridorKey**. Automatic setup requires macOS 26 or later. It downloads about 2.8 GB for the runtime and 720p model. To install both models in one pass, check **Also download the 1536 × 1024 model** before clicking **Download and Install**. The combined download is about 4.1 GB.
3. In the scene compositor or a Sequencer strip’s Compositor modifier, choose **Add → Keying → CorridorKey2.0 (MLX)**. Connect the footage to **Image**, choose a model resolution and frame range, then click **Analyze**. The frame range fills from the strip, the linked Image node, or the scene. The bake fits the source into the selected canvas without stretching it.

### Hints, masks, and outputs

Before analysis, the **Image** output previews the source. Under **More → Alpha Hint Settings**, connect a rough matte to **Alpha Hint**. The hint appears as a translucent white overlay. **Hint Frames** defaults to **First Frame**, which samples at **Start Frame**. Choose **All Frames** for an animated matte. **Alpha Hint Confidence** defaults to 0.8. Set it to zero to skip the hint. The **Garbage Mask** darkens excluded areas in the preview.

**Screen** selects green or blue despill. **Despill Strength** under **More** defaults to 1.0 and affects the baked **Image** and **Despilled Foreground**. Set it to zero to skip spill removal. **More → Additional Outputs** contains Matte, Despilled Foreground, Raw Foreground, and Edges.

Connect **Image** to the **Foreground** input of an **Alpha Over** node, or to **Group Output → Image** to replace a Sequencer strip’s image. Click **Clear Bake** to return to the source preview and change the settings before running **Analyze** again.

### Model resolutions

Both model resolutions use mixed FP16. The **1280 × 720** setting bakes into a 1280 × 720 canvas and the backend pads it to 1280 × 768 for inference. The image input can bake larger or smaller sources at the selected working resolution.

For the **1536 × 1024** setting, click **Download 1536 × 1024 Model** in the add-on preferences. It adds the profile to your active model folder and reuses matching weights from the installed 720p profile. With the 720p model already installed, the additional download is about 1.33 GB. A 16:9 source fits into this canvas at 1536 × 864, with space above and below.

### Custom paths and cache

Setup stores the runtime and models in Blender’s per-extension user folder. Analysis runs locally. To use an existing backend, set the MLX executable and model folder under **Advanced**. Clear both fields to use the managed setup.

**Cache folder** under **Advanced** overrides the default `corridorkey-cache` next to the blend file. Unsaved projects use the extension’s local analysis cache. The node reads the cache during playback and render, so keep it with the project. **Clear Bake** keeps the files by default. **Delete Cache Files on Clear Bake** under **Advanced** also removes them. Undo cannot recover deleted files, and other blend files may still use them.

If setup fails, check the `setup-*.log` path reported in Blender. For bake or inference failures, check `analysis.log` inside the job’s cache folder.

![Extension preferences](../images/settings.webp)
![Download dialog](../images/download.webp)
