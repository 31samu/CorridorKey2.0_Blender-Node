# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender preferences and progress for the MPS runtime installer."""

import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import uuid

import bpy

from .setup_runtime import installed_paths

ADDON_ID = __package__
MODEL_LICENSE = "https://huggingface.co/nikopueringer/CorridorKey2.0/blob/main/LICENSE"
active_setup = None


def runtime_root(create=False):
    path = bpy.utils.extension_path_user(ADDON_ID, path="runtime-1", create=create)
    if not path:
        raise OSError("Could not locate CorridorKey's extension storage.")
    return Path(path)


def managed_paths():
    try:
        return installed_paths(runtime_root())
    except OSError:
        return None


def analysis_paths(prefs):
    if prefs.mps_python or prefs.mps_checkout:
        if not prefs.mps_python or not prefs.mps_checkout:
            raise ValueError("Set both Advanced MPS paths or clear both to use automatic setup.")
        python = Path(bpy.path.abspath(prefs.mps_python)).expanduser().absolute()
        checkout = Path(bpy.path.abspath(prefs.mps_checkout)).expanduser().resolve()
        ffmpeg = "ffmpeg"
    else:
        paths = managed_paths()
        if paths is None:
            raise ValueError("Click Set Up CorridorKey in the extension preferences first.")
        python, checkout, ffmpeg = paths
    if prefs.mps_ffmpeg:
        ffmpeg = Path(bpy.path.abspath(prefs.mps_ffmpeg)).expanduser()
    return python, checkout, ffmpeg


class CorridorKeySetup(bpy.types.Operator):
    bl_idname = "preferences.corridorkey_mps_setup"
    bl_label = "Set Up CorridorKey"
    bl_description = "Install the PyTorch MPS runtime, FFmpeg, and original CorridorKey models"

    def invoke(self, context, event):
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Enable Allow Online Access in Blender's System preferences first.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=360, confirm_text="Download and Install")

    def draw(self, context):
        self.layout.label(text="Downloads Python, PyTorch, FFmpeg, and the model files.")
        self.layout.label(text="The download is several GB and is shared across resolutions.")
        self.layout.operator("wm.url_open", text="Model License", icon="URL").url = MODEL_LICENSE

    def execute(self, context):
        global active_setup
        if active_setup is not None or not bpy.app.online_access:
            return {"CANCELLED"}
        if sys.platform != "darwin" or platform.machine() != "arm64":
            self.report({"ERROR"}, "CorridorKey MPS setup requires Apple Silicon.")
            return {"CANCELLED"}
        try:
            root = runtime_root(create=True)
            self.log = root / f"setup-{uuid.uuid4().hex[:12]}.log"
            script = Path(__file__).with_name("setup_runtime.py")
            with self.log.open("wb") as log:
                self.process = subprocess.Popen(
                    [sys.executable, "-I", str(script), str(root)],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.message = "1/4 · Starting setup…"
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
            self.report({"ERROR"}, f"CorridorKey setup failed. See {self.log}")
            return {"CANCELLED"}
        self.report({"INFO"}, "CorridorKey MPS is ready.")
        return {"FINISHED"}

    def read_progress(self):
        try:
            with self.log.open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 32768))
                for line in reversed(log.read().splitlines()):
                    if line.startswith(b"SETUP "):
                        step, _, label = line[6:].decode(errors="replace").partition(" ")
                        self.message = f"{step}/4 · {label}"
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
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

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
        layout.label(text="MPS runtime and models installed", icon="CHECKMARK")
        if prefs.mps_python or prefs.mps_checkout or prefs.mps_ffmpeg:
            layout.label(text="Advanced paths override automatic setup.")
    elif not (prefs.mps_python and prefs.mps_checkout):
        layout.operator(CorridorKeySetup.bl_idname)
    try:
        root = runtime_root()
        if root.is_dir():
            layout.operator("wm.path_open", text="Open Downloaded Runtime Folder", icon="FILE_FOLDER").filepath = str(root)
    except OSError:
        pass


CLASSES = (CorridorKeySetup, CorridorKeySetupCancel)
