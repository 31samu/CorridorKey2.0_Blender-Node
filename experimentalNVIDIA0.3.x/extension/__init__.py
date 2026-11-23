# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, CompositorNodeCustomGroup, Operator

from . import cuda_backend, mlx_backend, process_control, setup_ui
from .sequences import DESPILLED_FOREGROUND, FOREGROUND_OUTPUTS, KEYED_FRAMES, SEQUENCE_NODES

ADDON_ID = __package__
NODE_ID = "CompositorNodeCorridorKeyMLX"
USE_CUDA = sys.platform == "win32"
NODE_LABEL = "CorridorKey2.0 (CUDA)" if USE_CUDA else "CorridorKey2.0 (MLX)"
JOBS = {}
ANALYSIS_BUSY_MESSAGE = "Wait for analysis to finish."
MORE_OUTPUTS = ("Matte", *FOREGROUND_OUTPUTS, "Edges")
ALPHA_HINT = "Alpha Hint"
GARBAGE_MASK = "Garbage Mask"
PREVIEW_NODE = "Mask Preview"
BAKE_PROGRESS = re.compile(rb"^Bake (\d+)/(\d+)$", re.MULTILINE)


def cache_root(prefs):
    if prefs.cache_root:
        return Path(bpy.path.abspath(prefs.cache_root)).expanduser().resolve()
    if bpy.data.filepath:
        return Path(bpy.data.filepath).parent / "corridorkey-cache"
    return setup_ui.runtime_root(cuda=USE_CUDA).parent / "analysis-cache"


def publish_sequences(node, sequences, start_frame, frame_count):
    located = [(sequence, *sequence.locate(frame_count)) for sequence in sequences]
    images = {}
    try:
        for sequence, first_frame, offset in located:
            image = bpy.data.images.load(str(first_frame), check_existing=False)
            images[sequence.node_name] = image, offset
            image.source = "SEQUENCE"
            image.filepath = str(first_frame)
            image.alpha_mode = sequence.alpha_mode
            if sequence.color_space is not None:
                image.colorspace_settings.name = sequence.color_space
    except Exception:
        for image, _ in images.values():
            bpy.data.images.remove(image)
        raise

    tree = node.node_tree
    for name, (image, offset) in images.items():
        source = tree.nodes[name]
        previous = source.image
        source.image = image
        source.frame_duration = frame_count
        source.frame_start = start_frame
        source.frame_offset = offset
        source.use_auto_refresh = True
        if previous and previous.users == 0:
            bpy.data.images.remove(previous)
    update_image_output(tree)


def set_start_frame(node, _context):
    if node.node_tree:
        for name in SEQUENCE_NODES:
            if source := node.node_tree.nodes.get(name):
                source.frame_start = node.start_frame


def has_bake(node):
    return node.node_tree.nodes[KEYED_FRAMES].image is not None


def image_path(image):
    return Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()


def bake_cache_directory(tree):
    keyed_path = image_path(tree.nodes[KEYED_FRAMES].image)
    result = keyed_path.parent.parent
    job = result.parent
    if result.name != "result" or not re.fullmatch(r"[0-9a-f]{32}", job.name):
        return None

    # The recorded path can be from before the project and cache were moved.
    config = json.loads((job / "bake.json").read_text())
    if not isinstance(config, dict):
        return None
    destination = config.get("destination")
    if not isinstance(destination, str) or Path(destination).parts[-2:] != (job.name, "baked-input"):
        return None

    layouts = (mlx_backend.output_sequences(result), cuda_backend.output_sequences(result))
    expected = {
        (sequence.node_name, sequence.folder, sequence.extension)
        for layout in layouts for sequence in layout
    }
    for name in SEQUENCE_NODES:
        image = tree.nodes[name].image
        if image:
            path = image_path(image)
            if (name, path.parent, path.suffix) not in expected:
                return None
    return job


class CorridorKeyPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    executable: StringProperty(name="MLX executable", subtype="FILE_PATH")
    model_root: StringProperty(name="FP16 model folder", subtype="DIR_PATH")
    cuda_python: StringProperty(name="CUDA Python", subtype="FILE_PATH")
    cuda_checkout: StringProperty(name="CorridorKey 2.0 folder", subtype="DIR_PATH")
    cuda_ffmpeg: StringProperty(name="FFmpeg executable", subtype="FILE_PATH", description="Optional when FFmpeg is on PATH")
    cache_root: StringProperty(name="Cache folder", subtype="DIR_PATH")
    delete_cache_on_clear: BoolProperty(
        name="Delete Cache Files on Clear Bake",
        description="Permanently delete the discarded bake's files. Undo and other blend files may still refer to them",
        default=False,
    )
    show_advanced: BoolProperty(name="Advanced", default=False)

    def draw(self, context):
        layout = self.layout
        setup_ui.draw_setup(layout, self)
        row = layout.row(align=True)
        row.alignment = "LEFT"
        row.prop(self, "show_advanced", emboss=False, icon="TRIA_DOWN" if self.show_advanced else "TRIA_RIGHT")
        if self.show_advanced:
            if USE_CUDA:
                layout.prop(self, "cuda_python")
                layout.prop(self, "cuda_checkout")
                layout.prop(self, "cuda_ffmpeg")
            else:
                layout.prop(self, "executable")
                layout.prop(self, "model_root")
            layout.prop(self, "cache_root")
            layout.prop(self, "delete_cache_on_clear")


class CorridorKeyNode(CompositorNodeCustomGroup):
    bl_idname = NODE_ID
    bl_label = NODE_LABEL

    screen: EnumProperty(
        name="Screen",
        items=mlx_backend.SCREEN_ITEMS,
    )
    start_frame: IntProperty(name="Start Frame", default=1, update=set_start_frame)
    bake_end: IntProperty(name="End Frame", default=1)
    profile: EnumProperty(
        name="Model resolution",
        items=mlx_backend.PROFILE_ITEMS,
    )
    status: StringProperty()

    def init(self, context):
        tree = bpy.data.node_groups.new("CorridorKey2.0", "CompositorNodeTree")
        tree.color_tag = "MATTE"
        image_input = tree.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketColor")
        image_input.hide_value = True
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        tree.interface.new_socket(name="Matte", in_out="OUTPUT", socket_type="NodeSocketFloat")
        image_node = tree.nodes.new("CompositorNodeImage")
        image_node.name = KEYED_FRAMES
        output = tree.nodes.new("NodeGroupOutput")
        output.location.x = 240
        add_processing_sockets(tree)
        organize_sockets(tree)
        add_mask_preview(tree)
        update_image_output(tree)
        self.node_tree = tree
        if USE_CUDA:
            self.outputs[DESPILLED_FOREGROUND].hide = True
        self.width = 245

    def copy(self, source_node):
        self.node_tree = source_node.node_tree.copy()

    def update(self):
        # Inserting a node into an existing wire can bypass insert_link.
        if self.is_property_set("start_frame") and self.is_property_set("bake_end"):
            return
        scene = getattr(bpy.context, "scene", None)
        # Blender validates the new link after calling update.
        link = image_input_link(self, require_valid=False)
        if scene and link is not None:
            set_source_range(self, scene, link.from_node)

    def draw_buttons(self, context, layout):
        job = JOBS.get(self.as_pointer())
        fields = layout.column()
        fields.enabled = job is None
        linked = image_is_linked(self)
        if USE_CUDA:
            fields.label(text="Green screen · Scene resolution")
        else:
            for property_name, label in (("screen", "Screen"), ("profile", "Model resolution")):
                field = fields.split(factor=0.52, align=True)
                field.label(text=label)
                field.prop(self, property_name, text="")
        fields.prop(self, "start_frame")
        fields.prop(self, "bake_end")
        if job:
            layout.operator("node.corridorkey_mlx_cancel", text="Cancel").node_name = self.name
            if job.progress is None:
                layout.label(text=job.message)
            else:
                layout.progress(factor=job.progress, type="BAR", text=job.message)
        elif has_bake(self):
            layout.operator("node.corridorkey_mlx_clear_bake", text="Clear Bake").node_name = self.name
            if self.status:
                layout.label(text=self.status)
        else:
            busy = bool(JOBS) and linked
            row = layout.row()
            row.enabled = linked and not busy
            row.operator(
                "node.corridorkey_mlx_analyze",
                text=ANALYSIS_BUSY_MESSAGE if busy else "Analyze",
            ).node_name = self.name
            if self.status and not busy:
                layout.label(text=self.status)


def add_processing_sockets(tree):
    for name, description in (
        (ALPHA_HINT, "Rough alpha for the first analyzed frame. A white overlay previews the foreground hint."),
        (GARBAGE_MASK, "White keeps the foreground. The preview darkens excluded areas before analysis."),
    ):
        socket = tree.interface.new_socket(
            name=name, in_out="INPUT", socket_type="NodeSocketFloat", description=description,
        )
        socket.hide_value = True
        socket.default_value = 1 if name == GARBAGE_MASK else 0
    for name, socket_type in (
        ("Despilled Foreground", "NodeSocketColor"),
        ("Raw Foreground", "NodeSocketColor"),
        ("Edges", "NodeSocketFloat"),
    ):
        tree.interface.new_socket(name=name, in_out="OUTPUT", socket_type=socket_type)

    nodes, links = tree.nodes, tree.links
    keyed = nodes[KEYED_FRAMES]
    output = next(node for node in nodes if node.type == "GROUP_OUTPUT" and node.is_active_output)
    group_input = nodes.new("NodeGroupInput")
    group_input.location.x = -240

    keep = nodes.new("ShaderNodeMath")
    keep.operation = "MULTIPLY"
    keep.use_clamp = True
    keep.inputs[0].default_value = 1
    links.new(group_input.outputs[GARBAGE_MASK], keep.inputs[1])

    masked_image = nodes.new("CompositorNodeSetAlpha")
    masked_image.name = "Masked Image"
    links.new(keyed.outputs["Image"], masked_image.inputs["Image"])
    links.new(keep.outputs[0], masked_image.inputs["Alpha"])

    matte = nodes.new("ShaderNodeMath")
    matte.operation = "MULTIPLY"
    links.new(keyed.outputs["Alpha"], matte.inputs[0])
    links.new(keep.outputs[0], matte.inputs[1])
    links.new(matte.outputs[0], output.inputs["Matte"])

    edges = nodes.new("ShaderNodeMath")
    edges.operation = "SUBTRACT"
    for index, size in enumerate((1, -1)):
        boundary = nodes.new("CompositorNodeDilateErode")
        boundary.inputs["Size"].default_value = size
        links.new(matte.outputs[0], boundary.inputs["Mask"])
        links.new(boundary.outputs["Mask"], edges.inputs[index])
    links.new(edges.outputs[0], output.inputs["Edges"])

    for name in FOREGROUND_OUTPUTS:
        foreground = nodes.new("CompositorNodeImage")
        foreground.name = name
        links.new(foreground.outputs["Image"], output.inputs[name])


def organize_sockets(tree):
    interface = tree.interface
    sockets = {
        (item.in_out, item.name): item for item in interface.items_tree
        if item.item_type == "SOCKET"
    }
    panel = interface.new_panel("More", default_closed=True)
    for index, name in enumerate(MORE_OUTPUTS):
        interface.move_to_parent(sockets["OUTPUT", name], panel, index)
    interface.move_to_parent(sockets["INPUT", ALPHA_HINT], panel, len(MORE_OUTPUTS))


def add_preview_mix(tree, label):
    mix = tree.nodes.new("ShaderNodeMix")
    mix.label = label
    mix.data_type = "RGBA"
    inputs = {socket.identifier: socket for socket in mix.inputs}
    result = next(socket for socket in mix.outputs if socket.identifier == "Result_Color")
    return inputs["Factor_Float"], inputs["A_Color"], inputs["B_Color"], result


def add_mask_preview(tree):
    group_input = next(node for node in tree.nodes if node.type == "GROUP_INPUT")
    image = group_input.outputs["Image"]
    links = tree.links

    strength = tree.nodes.new("ShaderNodeMath")
    strength.label = "Alpha Hint Preview Strength"
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 0.65
    links.new(group_input.outputs[ALPHA_HINT], strength.inputs[0])
    hint_factor, hint_source, hint_color, hinted = add_preview_mix(tree, "Preview Alpha Hint")
    links.new(strength.outputs[0], hint_factor)
    links.new(image, hint_source)
    hint_color.default_value = (1, 1, 1, 1)

    darkened = tree.nodes.new("CompositorNodeExposure")
    darkened.label = "Darken Excluded Areas"
    darkened.inputs["Exposure"].default_value = -4
    links.new(image, darkened.inputs["Image"])
    keep_factor, excluded, kept, preview_image = add_preview_mix(tree, "Preview Garbage Mask")
    links.new(group_input.outputs[GARBAGE_MASK], keep_factor)
    links.new(darkened.outputs["Image"], excluded)
    links.new(hinted, kept)

    original = tree.nodes.new("CompositorNodeSeparateColor")
    links.new(image, original.inputs["Image"])
    preview = tree.nodes.new("CompositorNodeSetAlpha")
    preview.name = PREVIEW_NODE
    preview.inputs["Type"].default_value = "Replace Alpha"
    links.new(preview_image, preview.inputs["Image"])
    links.new(original.outputs["Alpha"], preview.inputs["Alpha"])


def update_image_output(tree):
    keyed = tree.nodes[KEYED_FRAMES]
    output = next(node for node in tree.nodes if node.type == "GROUP_OUTPUT" and node.is_active_output)
    image_input = output.inputs["Image"]
    if keyed.image:
        source = tree.nodes["Masked Image"].outputs["Image"]
    elif preview := tree.nodes.get(PREVIEW_NODE):
        source = preview.outputs["Image"]
    else:
        group_input = next(node for node in tree.nodes if node.type == "GROUP_INPUT")
        source = group_input.outputs["Image"]
    if not any(link.from_socket == source for link in image_input.links):
        tree.links.new(source, image_input)


def image_input_link(node, require_valid=True, socket_name="Image"):
    socket = node.inputs.get(socket_name)
    if socket is not None:
        return next(
            (link for link in socket.links if not link.is_muted and (link.is_valid or not require_valid)),
            None,
        )
    return None


def image_is_linked(node):
    return image_input_link(node) is not None


def strip_compositor(scene, tree):
    editor = scene.sequence_editor
    strip = editor.active_strip if editor else None
    if strip:
        for modifier in strip.modifiers:
            if modifier.type == "COMPOSITOR" and modifier.node_group == tree:
                return strip, modifier
    return None, None


def set_source_range(node, scene, source):
    strip, _ = strip_compositor(scene, node.id_data)
    if strip:
        first, last = int(strip.frame_final_start), int(strip.frame_final_end) - 1
    else:
        visited = set()
        while source.type == "REROUTE" and source not in visited:
            visited.add(source)
            link = next((link for link in source.inputs[0].links if link.is_valid and not link.is_muted), None)
            if link is None:
                break
            source = link.from_node
        if source.bl_idname == "CompositorNodeImage" and source.image:
            first = source.frame_start
            if source.image.source == "MOVIE":
                duration = source.image.frame_duration
            elif source.image.source == "SEQUENCE":
                duration = source.frame_duration
            else:
                duration = 1
            last = first + max(duration, 1) - 1
        else:
            first, last = scene.frame_start, scene.frame_end
    # Keep any explicit range already entered on the node.
    if not node.is_property_set("start_frame"):
        node.start_frame = first
    if not node.is_property_set("bake_end"):
        node.bake_end = max(node.start_frame, last)


def bake_config(context, node, destination, bake_size):
    scene = context.scene
    editor = context.space_data
    tree = node.id_data
    if editor.node_tree != tree:
        raise ValueError("Place CorridorKey at the top level of the scene compositor or strip modifier.")
    link = image_input_link(node)
    if link is None:
        raise ValueError("Connect the Image input before analyzing.")
    set_source_range(node, scene, link.from_node)
    last = node.bake_end
    if last < node.start_frame:
        raise ValueError("End Frame must be at or after Start Frame.")
    width, height = bake_size
    config = {
        "scene": scene.name, "node": node.name, "first": node.start_frame,
        "last": last, "width": width, "height": height,
        "destination": str(destination / "baked-input"),
        "source_node": link.from_node.name,
        "source_socket": link.from_socket.identifier,
    }
    if hint := image_input_link(node, socket_name=ALPHA_HINT):
        config["hint"] = {
            "node": hint.from_node.name,
            "socket": hint.from_socket.identifier,
            "path": str(destination / "matte-hint.png"),
        }
    strip, modifier = strip_compositor(scene, tree)
    if strip:
        if strip not in scene.sequence_editor.strips[:]:
            raise ValueError("Linked baking is available on top-level strips.")
        if not strip.frame_final_start <= node.start_frame <= last < strip.frame_final_end:
            raise ValueError("Set Start and End Frame inside the selected strip.")
        return dict(config, context="strip", strip=strip.name, effect=modifier.name)
    for index, effect in enumerate(scene.compositor_effects):
        if effect.node_group == tree:
            return dict(config, context="effect", effect=index)
    if scene.compositing_node_group == tree:
        return dict(config, context="scene")
    raise ValueError("Open the scene compositor or select the strip that uses this compositor modifier.")


def get_node(context, name):
    tree = getattr(context.space_data, "edit_tree", None)
    node = tree.nodes.get(name) if tree else None
    return node if node and node.bl_idname == NODE_ID else None


def prepare_analysis(context, node, prefs, destination):
    output = destination / "result"
    if USE_CUDA:
        python, checkout, ffmpeg = setup_ui.cuda_analysis_paths(prefs)
        cuda_backend.validate_runtime(python, checkout, ffmpeg)
        render = context.scene.render
        percent = render.resolution_percentage
        bake_size = (max(4, render.resolution_x * percent // 100), max(4, render.resolution_y * percent // 100))
        config = bake_config(context, node, destination, bake_size)
        if config["context"] == "strip":
            raise ValueError("The experimental CUDA backend supports scene compositing only.")
        config["linear_color_space"] = cuda_backend.LINEAR_COLOR_SPACE
        command = cuda_backend.analysis_command(python, checkout, ffmpeg, config, output, render.fps / render.fps_base)
        return config, command, cuda_backend.output_sequences(output)

    executable, model_root = setup_ui.analysis_paths(prefs)
    mlx_backend.validate_runtime(executable, model_root, node.profile)
    config = bake_config(context, node, destination, mlx_backend.bake_size(node.profile))
    if config["context"] == "strip":
        config["python"] = str(mlx_backend.geometry_python(executable))
    command = mlx_backend.analysis_command(executable, model_root, config, output, node.screen, node.profile)
    return config, command, mlx_backend.output_sequences(output)


class CorridorKeyAnalyze(Operator):
    bl_idname = "node.corridorkey_mlx_analyze"
    bl_label = "Analyze with CorridorKey"
    bl_description = "Analyze the connected image and bake the keyed frames"

    node_name: StringProperty()

    def execute(self, context):
        if JOBS:
            self.report({"WARNING"}, ANALYSIS_BUSY_MESSAGE)
            return {"CANCELLED"}
        node = get_node(context, self.node_name)
        if not node:
            self.report({"ERROR"}, "Select a CorridorKey node.")
            return {"CANCELLED"}
        if has_bake(node):
            self.report({"WARNING"}, "Clear the bake before analyzing again.")
            return {"CANCELLED"}
        if not image_is_linked(node):
            return {"CANCELLED"}

        prefs = context.preferences.addons[ADDON_ID].preferences
        self.process = None
        self.snapshot = None
        try:
            destination = cache_root(prefs) / uuid.uuid4().hex
            config, self.analysis_command, self.sequences = prepare_analysis(context, node, prefs, destination)
            destination.mkdir(parents=True)
            self.destination = destination
            self.log = destination / "analysis.log"
            self.baking = True
            self.progress = None
            self.message = "1/3 · Saving bake project…"
            self.snapshot = destination / "bake.blend"
            config_path = destination / "bake.json"
            config_path.write_text(json.dumps(config))
            job = bpy.ops.wm.save_as_mainfile(
                filepath=str(self.snapshot), copy=True, relative_remap=True,
                check_existing=False, show_save_modified_images_dialog=False,
            )
            if "FINISHED" not in job:
                raise RuntimeError("Could not save a copy of the project for baking.")
            self.launch([
                bpy.app.binary_path, "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "1", str(self.snapshot),
                "--python", str(Path(__file__).with_name("bake_input.py")), "--", str(config_path),
            ])
        except (OSError, RuntimeError, ValueError) as error:
            self.remove_snapshot()
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.node = node
        self.node_pointer = node.as_pointer()
        self.start_frame = config["first"]
        self.frame_count = config["last"] - config["first"] + 1
        self.area = context.area
        self.window_manager = context.window_manager
        self.cancelled = False
        JOBS[self.node_pointer] = self
        node.status = "Waiting for analysis result."
        self.timer = self.window_manager.event_timer_add(0.25, window=context.window)
        self.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def launch(self, command):
        with self.log.open("ab") as log:
            self.process = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, cwd=self.destination,
                **process_control.launch_options(),
            )

    def remove_snapshot(self):
        if self.snapshot:
            try:
                self.snapshot.unlink(missing_ok=True)
            except OSError:
                pass

    def request_cancel(self):
        self.cancelled = True
        process_control.stop(self.process)

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if self.process.poll() is None:
            self.read_progress()
            return {"PASS_THROUGH"}
        if self.baking and self.process.returncode == 0 and not self.cancelled:
            self.remove_snapshot()
            self.baking = False
            self.progress = None
            self.message = "2/3 · Loading model…"
            try:
                self.launch(self.analysis_command)
            except OSError as error:
                self.report({"ERROR"}, str(error))
                return self.finish(launch_failed=True)
            try:
                self.area.tag_redraw()
            except ReferenceError:
                pass
            return {"RUNNING_MODAL"}
        return self.finish()

    def read_progress(self):
        try:
            with self.log.open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 16384))
                data = log.read()
            if self.baking:
                matches = BAKE_PROGRESS.findall(data)
                progress = (1, "Baking input", *map(int, matches[-1])) if matches else None
            else:
                progress = cuda_backend.read_progress(data) if USE_CUDA else mlx_backend.read_progress(data)
            if progress is not None:
                step, label, current, total = progress
                self.progress = min(current / max(total, 1), 1.0)
                self.message = f"{step}/3 · {label} {current}/{total}"
            self.area.tag_redraw()
        except (OSError, ReferenceError):
            pass

    def finish(self, launch_failed=False):
        self.window_manager.event_timer_remove(self.timer)
        JOBS.pop(self.node_pointer, None)
        self.remove_snapshot()
        try:
            if self.cancelled:
                self.node.status = "Analysis cancelled."
                return {"CANCELLED"}
            if launch_failed or self.process.returncode:
                self.node.status = "Bake failed. See analysis.log." if self.baking else "Analysis failed. See analysis.log."
                self.report({"ERROR"}, f"CorridorKey failed. See {self.log}")
                return {"CANCELLED"}

            publish_sequences(self.node, self.sequences, self.start_frame, self.frame_count)
            self.node.status = f"{self.frame_count} frames analysed"
            return {"FINISHED"}
        except (OSError, RuntimeError, ValueError) as error:
            self.node.status = "Could not load the result."
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except ReferenceError:
            return {"CANCELLED"}
        finally:
            try:
                self.area.tag_redraw()
            except ReferenceError:
                pass

    def cancel(self, context):
        self.request_cancel()
        self.remove_snapshot()
        self.window_manager.event_timer_remove(self.timer)
        JOBS.pop(self.node_pointer, None)
        try:
            self.node.status = "Analysis cancelled."
        except ReferenceError:
            pass


class CorridorKeyCancel(Operator):
    bl_idname = "node.corridorkey_mlx_cancel"
    bl_label = "Cancel CorridorKey analysis"

    node_name: StringProperty()

    def execute(self, context):
        node = get_node(context, self.node_name)
        if node and (job := JOBS.get(node.as_pointer())):
            job.request_cancel()
            return {"FINISHED"}
        return {"CANCELLED"}


class CorridorKeyClearBake(Operator):
    bl_idname = "node.corridorkey_mlx_clear_bake"
    bl_label = "Clear Bake"
    bl_description = "Clear this node's bake and return to the source preview. See preferences for cache deletion"
    bl_options = {"UNDO"}

    node_name: StringProperty()

    def execute(self, context):
        node = get_node(context, self.node_name)
        if not node or node.as_pointer() in JOBS or not has_bake(node):
            return {"CANCELLED"}
        prefs = context.preferences.addons[ADDON_ID].preferences
        delete_cache = prefs.delete_cache_on_clear
        if delete_cache and JOBS:
            self.report({"WARNING"}, ANALYSIS_BUSY_MESSAGE)
            return {"CANCELLED"}

        tree = node.node_tree
        directory = None
        if delete_cache:
            try:
                directory = bake_cache_directory(tree)
            except (OSError, ValueError):
                pass
            if directory is None:
                self.report({"WARNING"}, "CorridorKey could not identify this bake's cache. Files were kept.")

        for name in SEQUENCE_NODES:
            source = tree.nodes[name]
            image = source.image
            source.image = None
            if image and image.users == 0:
                bpy.data.images.remove(image)
        update_image_output(tree)
        node.status = ""
        if directory is not None:
            try:
                if any(
                    image.users and image.filepath and image_path(image).is_relative_to(directory)
                    for image in bpy.data.images
                ):
                    self.report({"WARNING"}, "Cache files were kept because this project still uses them.")
                else:
                    shutil.rmtree(directory)
            except OSError as error:
                self.report({"WARNING"}, f"Could not delete the bake cache: {error}")
        return {"FINISHED"}


def draw_keying_menu(self, context):
    operator = self.layout.operator("node.add_node", text=NODE_LABEL)
    operator.type = NODE_ID
    operator.use_transform = True


CLASSES = (
    *setup_ui.CLASSES, CorridorKeyPreferences, CorridorKeyNode,
    CorridorKeyAnalyze, CorridorKeyCancel, CorridorKeyClearBake,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_category_compositor_keying.append(draw_keying_menu)


def unregister():
    if setup_ui.active_setup is not None:
        setup_ui.active_setup.cancel(None)
    for job in tuple(JOBS.values()):
        job.cancel(None)
    bpy.types.NODE_MT_category_compositor_keying.remove(draw_keying_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
