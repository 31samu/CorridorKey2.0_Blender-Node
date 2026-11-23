# Setup

Install the experimental extension ZIP in Blender 5.3 or later via **Preferences → Get Extensions → Install from Disk**. It uses the same extension ID as the Mac release, so installing this build replaces that copy and reuses its installed MLX runtime and models.

On Mac and Windows, **Preferences → Add-ons → CorridorKey Node (Experimental) → Open Downloaded Runtime Folder** opens the managed setup folder once it exists, even if setup did not finish. It does not open manually configured paths or the analysis cache. To remove the downloads, open the folder, quit Blender, then delete the folder in Finder or Explorer.

## Windows with NVIDIA (experimental)

Use 64-bit Windows and an NVIDIA RTX 30-series or newer GPU with a current driver that supports CUDA 12.8. Allow at least 12 GB of free space for setup and enable **Allow Online Access** in Blender's System preferences. [Upstream GPU requirements](https://github.com/nikopueringer/CorridorKey2.0#setup)

1. Under **Preferences → Add-ons → CorridorKey Node (Experimental)**, click **Set Up CorridorKey**, then **Download and Install**.
2. Wait for **CUDA runtime and models installed**. Setup downloads several gigabytes and installs Python, PyTorch with CUDA, FFmpeg, and the CorridorKey runtime and weights in `%LOCALAPPDATA%\CorridorKeyBlender\cuda-1`. Analysis uses these files automatically. No terminal commands or separate Python, Git, or FFmpeg installation are needed.
3. Add **Keying → CorridorKey2.0 (CUDA)** in the scene compositor and connect a short green-screen clip. Set a small frame range and click **Analyze**.

If setup fails, Blender reports the location of `setup-*.log` in the runtime folder. A previous manual installation can still be selected under **Advanced**. Clear **CUDA Python**, **CorridorKey 2.0 folder**, and **FFmpeg executable** to return to the managed installation.

For the first test, set the scene render size to 1280 × 720 at 100%. The node uses the scene's render size including the resolution percentage. Its input and output plates are scene-linear EXR in Linear Rec.709. The Windows node supports green screen and exposes **Image**, **Matte**, **Raw Foreground**, and **Edges** in the scene compositor.

For a Windows test report, include the GPU, driver, Blender and extension versions, and the relevant log. Send `setup-*.log` for an installation failure or `analysis.log` for an analysis failure. Check frame alignment and alpha, then try canceling a longer analysis and running it again. Automatic setup and CUDA inference still need a test on actual Windows RTX hardware.

## macOS with Apple Silicon

In **Preferences → Add-ons**, expand **CorridorKey Node (Experimental)** and click **Set Up CorridorKey**. To install both profiles in one pass, check **Also download the 1536 × 1024 model** before clicking **Download and Install**. Automatic setup requires Apple Silicon, macOS 26 or later, and Blender's **Allow Online Access** setting. A fresh install downloads about 2.8 GB for the runtime and 720p model, or about 4.1 GB with both models. Setup stores the runtime and models in Blender's per-extension user folder. Subsequent analysis runs locally.

If you already have a working backend, use the executable and model folder fields under **Advanced**. Clear both fields to use automatic setup. The **Cache folder** override is also under **Advanced**. Unsaved projects use the extension's local analysis cache.

## Use the node

1. In the scene compositor, choose **Add → Keying → CorridorKey2.0** with your platform's **CUDA** or **MLX** label and connect its **Image** input. On Mac, the node also works in a Sequencer strip's Compositor modifier. **Start Frame** and **End Frame** fill from the strip's visible range or the linked Image node's media. For other graphs, they use the scene range. The bake fits the source without stretching it.
2. Before analysis, the **Image** output previews the source. The **Alpha Hint** under **More** adds a translucent white overlay. The **Garbage Mask** darkens excluded areas, including where the two masks overlap.
3. Click **Analyze**. The node shows frame counts as it bakes, analyzes, and keys. Connect its **Image** output to the **Foreground** input of an **Alpha Over** node, or to **Group Output → Image** to replace a Sequencer strip's image.
4. Click **Clear Bake** to return to the source preview before analyzing again. The cached files stay on disk by default. Enable **Delete Cache Files on Clear Bake** under **Advanced** in the add-on preferences to remove them as well. Undo can't recover deleted files, and other saved blend files may still need them. If a job fails, look for `analysis.log` in the job folder within the cache directory. The default cache is `corridorkey-cache` next to the saved blend file.

## MLX model resolutions

The installed 720p FP16 profile has a padded height × width of 768 × 1280. Model graphs use fixed tensor shapes. Image input can bake larger or smaller sources at the selected working resolution.

For the extension's **1536 × 1024** setting, click **Download 1536 × 1024 Model** in the add-on preferences. It adds the profile to your active model folder and reuses weights that match files in the installed 720p profile. A complete 720p install reduces the additional download to about 1.33 GB. 

Native 1920 × 1080 needs a 1152 × 1920 graph. Native 3840 × 2160 needs a 2176 × 3840 graph. Those profiles would need to be converted and validated for the MLX runtime, or supplied by the model maintainer. Then the extension would need to expose them.

The node reads the analysis cache during playback and render. Keep the cache with the project. The cache uses a new folder for each analysis, so you can remove earlier folders once any blend files that reference them have been retired.

![MLX extension settings](../images/settings.webp)
![MLX download dialog](../images/download.webp)
