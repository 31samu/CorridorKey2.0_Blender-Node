# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender preferences and progress for the platform's PyTorch installer."""

import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import bpy

from . import process_control
from .torch_backend import BACKEND_NAME, USE_CUDA

if USE_CUDA:
    from . import setup_cuda_runtime as installer
else:
    from . import setup_runtime as installer

ADDON_ID = __package__
MODEL_LICENSE = "https://huggingface.co/nikopueringer/CorridorKey2.0/blob/main/LICENSE"
active_setup = None


def runtime_root(create=False):
    if USE_CUDA and (local := os.environ.get("LOCALAPPDATA")):
        path = Path(local) / "CorridorKeyBlender" / "cuda-1"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path
    folder = "cuda-1" if USE_CUDA else "runtime-1"
    path = bpy.utils.extension_path_user(ADDON_ID, path=folder, create=create)
    if not path:
        raise OSError("Could not locate CorridorKey's extension storage.")
    return Path(path)


def managed_paths():
    try:
        return installer.installed_paths(runtime_root())
    except OSError:
        return None


def analysis_paths(prefs):
    if prefs.runtime_python or prefs.runtime_checkout:
        if not prefs.runtime_python or not prefs.runtime_checkout:
            raise ValueError(f"Set both Advanced {BACKEND_NAME} paths or clear both to use automatic setup.")
        python = Path(bpy.path.abspath(prefs.runtime_python)).expanduser().absolute()
        checkout = Path(bpy.path.abspath(prefs.runtime_checkout)).expanduser().resolve()
        ffmpeg = "ffmpeg"
    else:
        paths = managed_paths()
        if paths is None:
            raise ValueError("Click Set Up CorridorKey in the extension preferences first.")
        python, checkout, ffmpeg = paths
    if prefs.runtime_ffmpeg:
        ffmpeg = Path(bpy.path.abspath(prefs.runtime_ffmpeg)).expanduser()
    return python, checkout, ffmpeg


class CorridorKeySetup(bpy.types.Operator):
    bl_idname = "preferences.corridorkey_mps_setup"
    bl_label = "Set Up CorridorKey"
    bl_description = f"Install the PyTorch {BACKEND_NAME} runtime, FFmpeg, and original CorridorKey models"

    build_native: bpy.props.BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.build_native:
            return "Compile and test the optional MPSGraph attention library using Apple's developer tools"
        return cls.bl_description

    def invoke(self, context, event):
        if self.build_native:
            return self.execute(context)
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Enable Allow Online Access in Blender's System preferences first.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=360, confirm_text="Download and Install")

    def draw(self, context):
        self.layout.label(text="Downloads Python, PyTorch, FFmpeg, and the model files.")
        self.layout.label(text="The download is several GB and is shared across resolutions.")
        if USE_CUDA:
            self.layout.label(text="Allow 12 GB free. Requires an RTX 30-series or newer GPU.")
        self.layout.operator("wm.url_open", text="Model License", icon="URL").url = MODEL_LICENSE

    def execute(self, context):
        global active_setup
        if active_setup is not None or (not self.build_native and not bpy.app.online_access):
            return {"CANCELLED"}
        if USE_CUDA:
            if self.build_native or platform.machine().lower() not in {"amd64", "x86_64"}:
                self.report({"ERROR"}, "CUDA setup requires x64 Windows. Native attention setup is for Apple Silicon.")
                return {"CANCELLED"}
        elif sys.platform != "darwin" or platform.machine() != "arm64":
            self.report({"ERROR"}, "CorridorKey MPS setup requires Apple Silicon.")
            return {"CANCELLED"}
        try:
            root = runtime_root(create=True)
            label = "native-attention" if self.build_native else "setup"
            self.log = root / f"{label}-{uuid.uuid4().hex[:12]}.log"
            command = [sys.executable, "-I", "-X", "utf8", installer.__file__, str(root)]
            if self.build_native:
                command.append("--native-attention")
            with self.log.open("wb") as log:
                self.process = subprocess.Popen(
                    command,
                    stdout=log, stderr=subprocess.STDOUT, **process_control.launch_options(),
                )
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.steps = 2 if self.build_native else 4
        self.message = f"1/{self.steps} · Starting setup…"
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
            return {"CANCELLED"}
        if result != 0 or managed_paths() is None:
            label = "Native attention build" if self.build_native else "CorridorKey setup"
            self.report({"ERROR"}, f"{label} failed. See {self.log}")
            return {"CANCELLED"}
        if self.build_native:
            context.preferences.addons[ADDON_ID].preferences.native_attention = True
            self.report({"INFO"}, "Native MPSGraph attention is ready.")
        else:
            self.report({"INFO"}, f"CorridorKey {BACKEND_NAME} is ready.")
        return {"FINISHED"}

    def read_progress(self):
        try:
            with self.log.open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 32768))
                for line in reversed(log.read().splitlines()):
                    if line.startswith(b"SETUP "):
                        step, _, label = line[6:].decode(errors="replace").partition(" ")
                        self.message = f"{step}/{self.steps} · {label}"
                        break
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
    bl_idname = "preferences.corridorkey_mps_setup_cancel"
    bl_label = "Cancel Setup"

    def execute(self, context):
        if active_setup is None:
            return {"CANCELLED"}
        active_setup.stop()
        return {"FINISHED"}


def draw_setup(layout, prefs):
    if active_setup is not None:
        layout.label(text=active_setup.message)
        layout.operator(CorridorKeySetupCancel.bl_idname)
    elif managed_paths() is not None:
        layout.label(text=f"{BACKEND_NAME} runtime and models installed", icon="CHECKMARK")
        if prefs.runtime_python or prefs.runtime_checkout or prefs.runtime_ffmpeg:
            layout.label(text="Advanced paths override automatic setup.")
    elif not (prefs.runtime_python and prefs.runtime_checkout):
        layout.operator(CorridorKeySetup.bl_idname)
    try:
        root = runtime_root()
        if root.is_dir():
            layout.operator("wm.path_open", text="Open Downloaded Runtime Folder", icon="FILE_FOLDER").filepath = str(root)
    except OSError:
        pass


def draw_native_attention(layout, prefs):
    layout.prop(prefs, "native_attention")
    paths = managed_paths()
    if paths is None or prefs.runtime_python or prefs.runtime_checkout:
        return
    build = paths[1] / "corridorkey/native/build"
    installed = (build / "mps_attention.so").is_file() and (build / "torch-version.txt").is_file()
    row = layout.row()
    row.enabled = active_setup is None
    text = "Rebuild Native Attention" if installed else "Build Native Attention"
    row.operator(CorridorKeySetup.bl_idname, text=text).build_native = True
    if not installed:
        layout.label(text="macOS 15+ and Apple developer tools required.")


CLASSES = (CorridorKeySetup, CorridorKeySetupCancel)
