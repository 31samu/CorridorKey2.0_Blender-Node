# AGENTS.md

## Working in this repo

- Treat the codebase as the source of truth. Verify comments, docs, and claims from prior conversations or external sources against the implementation before relying on them. Start with the source tree for the build you are changing.

## Where changes go

- `extension/` is the default Apple Silicon release source. `experimentalNVIDIA0.3.x/extension/` is the older MLX and Windows CUDA build. Keep its base Mac version and experimental suffix in sync with the code it uses. `0.5.xMPS/extension/` is the Apple Silicon MPS edition.

- Put release-facing usage and installation docs in `README.md` and `Setup.md` for each build. Put documentation images in `images/`.
- Use the workspace's sibling `../test-footage/` for local clips and blend files, and `../.setup/` for temporary Blender probes and logs. Keep generated frames, analysis caches, model weights, and installed runtimes outside the repository. Saved blend files can reference analysis caches, so check before deleting caches or changing their layout.
- Keep old versions of the extension in the workspace's sibling `../oldVersions/` for easy future reference.
- The sibling `../corridorkey-v2-mlx/` is a local upstream reference. The add-on's MLX installer fetches a pinned backend revision. Check `setup_runtime.py` and `mlx_backend.py` before assuming that edits to the sibling copy affect the installed add-on.

## Build and check

- Use Blender 5.3 or later. From the repository root, run `blender --factory-startup --command extension validate` with the affected extension source directory. On macOS, use `/Applications/Blender.app/Contents/MacOS/Blender` if `blender` is unavailable on your PATH.
- Build an install test with `blender --factory-startup --command extension build --source-dir extension --output-dir /tmp`. Substitute the affected source directory. Stable MLX and the older NVIDIA build share an extension ID. The MPS edition has its own ID and can be installed alongside stable MLX.
- For node changes, analyze a short clip in the scene compositor. Also check a Sequencer strip compositor on MLX when the change affects that path. Check the affected outputs, frame alignment, and playback after reopening the blend file when changing sequence paths or cache handling. For job lifecycle changes, check cancel and rerun. For setup failures, inspect the setup log. For analysis failures, inspect `analysis.log` in the job folder.
- Report which build, platform, and behavior you tested. Apple Silicon can exercise MLX and MPS. CUDA runtime and inference checks for the Windows build require Windows with a supported NVIDIA GPU.
- Build test ZIPs outside the repo. Update tracked ZIPs when the task calls for packaging a release. `UNZIPME.zip` bundles the Mac install ZIP with `README.md` and `Setup.md`. The experimental ZIP is installed directly.

## Performance testing

- Record performance measurements in `performance.md` with the hardware, runtime, frame count, working resolution, temporal settings, and timed scope.
