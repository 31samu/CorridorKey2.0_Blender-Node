# AGENTS.md

## Working in this repo

- Treat the codebase as the source of truth. Verify comments, docs, and claims from prior conversations or external sources against the implementation before relying on them. Start with the source tree for the build you are changing.

## Where changes go

- `mlx/extension/` is the default Apple Silicon release source. `pytorch/extension/` is the PyTorch edition for Apple Silicon MPS and experimental Windows CUDA.
- During early development, skip migrations for obsolete node layouts unless the user asks for them.

- Put release-facing usage and installation docs in `README.md` and `Setup.md` for each build. Put documentation images in `images/`.
- Use the workspace's sibling `../test-footage/` for local clips and blend files, and `../.setup/` for temporary Blender probes and logs. Keep generated frames, analysis caches, model weights, and installed runtimes outside the repository. Saved blend files can reference analysis caches, so check before deleting caches or changing their layout.
- Keep old versions of the extension in the workspace's sibling `../oldVersions/` for easy future reference.
- The sibling `../corridorkey-v2-mlx/` is a local upstream reference. The add-on's MLX installer fetches a pinned backend revision. Check `setup_runtime.py` and `mlx_backend.py` before assuming that edits to the sibling copy affect the installed add-on.

## Build and check

- For small extension changes such as UI refinements, default changes, and bug fixes, increment the patch version in the affected `blender_manifest.toml` unless the user specifies a different version. When packaging the build, keep the ZIP filename and download links in sync with the manifest.
- Use Blender 5.3 or later. From the repository root, run `blender --factory-startup --command extension validate` with the affected extension source directory. On macOS, use `/Applications/Blender.app/Contents/MacOS/Blender` if `blender` is unavailable on your PATH.
- Build an install test with `blender --factory-startup --command extension build --source-dir mlx/extension --output-dir /tmp`. Use `pytorch/extension` for the PyTorch build. The editions have separate extension IDs and can be installed together.
- For node changes, analyze a short clip in the scene compositor. Also check a Sequencer strip compositor on MLX when the change affects that path. Check the affected outputs, frame alignment, and playback after reopening the blend file when changing sequence paths or cache handling. For job lifecycle changes, check cancel and rerun. For setup failures, inspect the setup log. For analysis failures, inspect `analysis.log` in the job folder.
- Report which build, platform, and behavior you tested. Apple Silicon can exercise MLX and MPS. CUDA runtime and inference checks for the Windows build require Windows with a supported NVIDIA GPU.
- Build test ZIPs outside the repo. Update tracked ZIPs when the task calls for packaging a release. Put each install ZIP next to its edition’s `README.md` and `Setup.md`.

## Performance testing

- Record performance measurements in `performance.md` with the hardware, runtime, frame count, working resolution, temporal settings, and timed scope.
