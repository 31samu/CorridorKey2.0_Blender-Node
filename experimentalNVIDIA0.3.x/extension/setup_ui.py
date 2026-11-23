# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender preferences and monitor for the standalone setup process."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import bpy

from .mlx_backend import LARGE_MODEL_FILES, large_model_ready
from . import process_control, setup_cuda_runtime

ADDON_ID = __package__
MODEL_FILES = json.loads(Path(__file__).with_name("setup-model-files.json").read_text())
MODEL_LICENSE = "https://huggingface.co/cdelta/CorridorKey-v2-MLX-fp16/blob/main/LICENSE"
CUDA_LICENSE = "https://huggingface.co/nikopueringer/CorridorKey2.0/blob/main/LICENSE"
WINDOWS = sys.platform == "win32"
active_setup = None


def setup_available():
    if WINDOWS:
        return platform.machine().lower() in {"amd64", "x86_64"}
    return platform.machine() == "arm64" and int(platform.mac_ver()[0].split(".")[0] or 0) >= 26


def runtime_root(create=False, cuda=False):
    if cuda and (local := os.environ.get("LOCALAPPDATA")):
        path = Path(local) / "CorridorKeyBlender" / "cuda-1"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path
    if cuda:
        path = bpy.utils.extension_path_user(ADDON_ID, path="cuda-1", create=create)
    else:
        path = bpy.utils.extension_path_user(ADDON_ID, path="runtime-1", create=create)
    if not path:
        raise OSError("Could not locate CorridorKey's extension storage.")
    return Path(path)


def managed_cuda_paths():
    try:
        return setup_cuda_runtime.installed_paths(runtime_root(cuda=True))
    except OSError:
        return None


def cuda_analysis_paths(prefs):
    if prefs.cuda_python or prefs.cuda_checkout:
        if not prefs.cuda_python or not prefs.cuda_checkout:
            raise ValueError("Set both Advanced CUDA paths or clear both to use automatic setup.")
        python = Path(bpy.path.abspath(prefs.cuda_python)).expanduser().absolute()
        checkout = Path(bpy.path.abspath(prefs.cuda_checkout)).expanduser().resolve()
        ffmpeg = "ffmpeg"
    else:
        paths = managed_cuda_paths()
        if paths is None:
            raise ValueError("Click Set Up CorridorKey in the extension preferences first.")
        python, checkout, ffmpeg = paths
    if prefs.cuda_ffmpeg:
        ffmpeg = bpy.path.abspath(prefs.cuda_ffmpeg)
    return python, checkout, ffmpeg


def managed_paths():
    try:
        root = runtime_root()
    except OSError:
        return None
    if (root / "ready").is_file():
        executable = root / "venv/bin/corridorkey-mlx"
        models = root / "models"
        if os.access(executable, os.X_OK) and all(
            (models / name).is_file() for name in MODEL_FILES
        ):
            return executable, models
    return None


def selected_model_root(prefs):
    if prefs.executable and prefs.model_root:
        return Path(bpy.path.abspath(prefs.model_root)).expanduser().resolve()
    if not (prefs.executable or prefs.model_root) and (paths := managed_paths()):
        return paths[1]
    return None


def analysis_paths(prefs):
    if prefs.executable or prefs.model_root:
        if not prefs.executable or not prefs.model_root:
            raise ValueError("Set both paths in Advanced preferences or clear both to use automatic setup.")
        executable = Path(bpy.path.abspath(prefs.executable)).expanduser().resolve()
        return executable, selected_model_root(prefs)
    paths = managed_paths()
    if paths is None:
        raise ValueError("Click Set Up CorridorKey in the extension preferences first.")
    return paths


class CorridorKeySetup(bpy.types.Operator):
    bl_idname = "preferences.corridorkey_setup"
    bl_label = "Set Up CorridorKey"
    bl_description = "Install the local runtime and download model weights"
    large_model: bpy.props.BoolProperty(options={"SKIP_SAVE"})
    include_large_model: bpy.props.BoolProperty(
        name="Also download the 1536 × 1024 model",
        description="Install the larger FP16 profile alongside the 720p model",
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, event):
        if not setup_available():
            requirement = "64-bit Windows on x86-64" if WINDOWS else "Apple Silicon and macOS 26 or later"
            self.report({"ERROR"}, f"Automatic setup requires {requirement}.")
            return {"CANCELLED"}
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Enable Allow Online Access in Blender's System preferences first.")
            return {"CANCELLED"}
        title = "Download 1536 × 1024 Model" if self.large_model else self.bl_label
        return context.window_manager.invoke_props_dialog(
            self, width=340, title=title, confirm_text="Download and Install",
        )

    def draw(self, context):
        column = self.layout.column(align=True)
        if WINDOWS:
            column.label(text="Installs Python, PyTorch CUDA, FFmpeg and models.")
            column.label(text="Download: several GB. Allow 12 GB free disk space.")
            column.label(text="Requires a compatible NVIDIA GPU and driver.")
        elif self.large_model:
            column.label(text="Reuses matching weights from the 720p model.")
            column.label(text="Download size: up to 2.54 GB")
        else:
            column.label(text="Includes the local runtime and 720p model.")
            column.prop(self, "include_large_model")
            size = "4.1 GB" if self.include_large_model else "2.8 GB"
            column.label(text=f"Download size: about {size}")
        self.layout.separator()
        row = self.layout.row()
        row.alignment = "LEFT"
        row.operator("wm.url_open", text="Model License", icon="URL").url = CUDA_LICENSE if WINDOWS else MODEL_LICENSE

    def execute(self, context):
        global active_setup
        if active_setup is not None or not bpy.app.online_access or not setup_available():
            return {"CANCELLED"}
        try:
            root = runtime_root(create=True, cuda=WINDOWS)
            script = "setup_cuda_runtime.py" if WINDOWS else "setup_runtime.py"
            command = [sys.executable, "-I", "-X", "utf8", str(Path(__file__).with_name(script)), str(root)]
            if not WINDOWS:
                self.model_root = selected_model_root(context.preferences.addons[ADDON_ID].preferences) if self.large_model else root / "models"
                if self.model_root is None:
                    raise OSError("Set up the runtime or configure both Advanced paths first.")
                if self.large_model:
                    command.append(str(self.model_root))
                elif self.include_large_model:
                    command.append("--include-large-model")
            self.log = root / f"setup-{uuid.uuid4().hex[:12]}.log"
            with self.log.open("wb") as log:
                self.process = subprocess.Popen(
                    command,
                    stdout=log, stderr=subprocess.STDOUT, **process_control.launch_options(),
                )
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.steps = 4 if WINDOWS or (self.include_large_model and not self.large_model) else 3
        self.step = "1"
        self.message = "Preparing model download…" if self.large_model else f"1/{self.steps} · Starting setup…"
        self.progress = None
        self.cancelled = False
        self.window_manager = context.window_manager
        self.area = context.area
        self.timer = self.window_manager.event_timer_add(0.5, window=context.window)
        self.window_manager.modal_handler_add(self)
        active_setup = self
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        result = self.process.poll()
        if result is None:
            self.read_progress()
            return {"PASS_THROUGH"}
        self.finish()
        if self.cancelled:
            self.report({"INFO"}, "Setup cancelled. Run it again to resume model downloads.")
            return {"CANCELLED"}
        ready = managed_cuda_paths() is not None if WINDOWS else self.large_model or managed_paths() is not None
        if not WINDOWS and (self.large_model or self.include_large_model):
            ready = ready and large_model_ready(self.model_root)
        if result != 0 or not ready:
            self.report({"ERROR"}, f"CorridorKey setup failed. See {self.log}")
            return {"CANCELLED"}
        if WINDOWS:
            message = "CorridorKey CUDA is ready."
        elif self.large_model:
            message = "1536 × 1024 model is ready."
        elif self.include_large_model:
            message = "CorridorKey 720p and 1536 × 1024 models are ready."
        else:
            message = "CorridorKey 720p is ready."
        self.report({"INFO"}, message)
        return {"FINISHED"}

    def read_progress(self):
        try:
            with self.log.open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 32768))
                for line in reversed(log.read().splitlines()):
                    if line.startswith(b"SETUP "):
                        self.step, _, label = line[6:].decode(errors="replace").partition(" ")
                        prefix = "" if self.large_model else f"{self.step}/{self.steps} · "
                        self.message = prefix + label
                        break
            self.progress = None
            if not WINDOWS and self.step in {"2", "4"}:
                is_large = self.large_model or self.step == "4"
                files = LARGE_MODEL_FILES if is_large else MODEL_FILES
                total = sum(metadata["size"] for metadata in files.values())
                received = 0
                for name, metadata in files.items():
                    final = self.model_root / name
                    partial = final.with_name(final.name + ".part")
                    for path in (final, partial):
                        try:
                            received += min(path.stat().st_size, metadata["size"])
                            break
                        except FileNotFoundError:
                            continue
                self.progress = min(received / total, 1.0)
                prefix = "" if self.large_model else f"{self.step}/{self.steps} · "
                model = "1536 × 1024" if is_large else "720p"
                self.message = f"{prefix}{model} model files · {received / 1e9:.2f} / {total / 1e9:.2f} GB"
        except OSError:
            pass
        self.redraw()

    def redraw(self):
        try:
            if self.area is not None:
                self.area.tag_redraw()
        except ReferenceError:
            pass

    def stop(self):
        self.cancelled = True
        process_control.stop(self.process)

    def cancel(self, context):
        self.stop()
        self.finish()

    def finish(self):
        global active_setup
        self.window_manager.event_timer_remove(self.timer)
        active_setup = None
        self.redraw()


class CorridorKeySetupCancel(bpy.types.Operator):
    bl_idname = "preferences.corridorkey_setup_cancel"
    bl_label = "Cancel Setup"

    def execute(self, context):
        if active_setup is None:
            return {"CANCELLED"}
        active_setup.stop()
        return {"FINISHED"}


def draw_setup(layout, prefs):
    if active_setup is not None:
        if active_setup.progress is None:
            layout.label(text=active_setup.message)
        else:
            layout.progress(factor=active_setup.progress, type="BAR", text=active_setup.message)
        layout.operator(CorridorKeySetupCancel.bl_idname)
    elif WINDOWS:
        if managed_cuda_paths() is not None:
            layout.label(text="CUDA runtime and models installed", icon="CHECKMARK")
            if prefs.cuda_python or prefs.cuda_checkout or prefs.cuda_ffmpeg:
                layout.label(text="Advanced CUDA paths override automatic setup.")
        else:
            layout.operator(CorridorKeySetup.bl_idname)
    elif managed_paths() is not None:
        layout.label(text="720p model and runtime installed", icon="CHECKMARK")
        if prefs.executable or prefs.model_root:
            layout.label(text="Advanced paths override automatic setup.")
    elif not (prefs.executable and prefs.model_root):
        layout.operator(CorridorKeySetup.bl_idname)
    if not WINDOWS and active_setup is None and (models := selected_model_root(prefs)) and not large_model_ready(models):
        layout.operator(CorridorKeySetup.bl_idname, text="Download 1536 × 1024 Model").large_model = True
    try:
        root = runtime_root(cuda=WINDOWS)
        if root.is_dir():
            layout.operator("wm.path_open", text="Open Downloaded Runtime Folder", icon="FILE_FOLDER").filepath = str(root)
    except OSError:
        pass


CLASSES = (CorridorKeySetup, CorridorKeySetupCancel)
