# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake a compositor socket in a background copy of the project."""

import json
import math
from pathlib import Path
import subprocess
import sys

import bpy


def set_png_format(settings, view_transform):
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    settings.color_depth = "16"
    settings.display_settings.display_device = "sRGB"
    view = settings.view_settings
    view.view_transform = view_transform
    view.look = "None"
    view.exposure = 0
    view.gamma = 1
    view.use_curve_mapping = False
    view.use_white_balance = False


def set_plate_format(settings, color_space):
    if color_space is None:
        set_png_format(settings, "Standard")
        return ".png"
    settings.file_format = "OPEN_EXR"
    settings.color_mode = "RGB"
    settings.color_depth = "32"
    settings.linear_colorspace_settings.name = color_space
    if settings.linear_colorspace_settings.name != color_space:
        raise ValueError(f"The color configuration must provide {color_space} for CUDA input.")
    return ".exr"


def bake(config):
    scene = bpy.data.scenes[config["scene"]]
    context = config["context"]
    render = scene.render

    # A bake should only write its own image sequence, even if the project
    # contains File Output nodes or has stamping enabled.
    for tree in bpy.data.node_groups:
        if tree.bl_idname == "CompositorNodeTree":
            for node in list(tree.nodes):
                if node.type == "OUTPUT_FILE":
                    tree.nodes.remove(node)

    if context == "strip":
        editor = scene.sequence_editor
        strip = editor.strips[config["strip"]]
        elements = getattr(strip, "elements", ())
        if elements and elements[0].orig_width and elements[0].orig_height:
            render.resolution_x = elements[0].orig_width
            render.resolution_y = elements[0].orig_height
        render.resolution_percentage = 100
        render.pixel_aspect_x = render.pixel_aspect_y = 1
        for other_strip in editor.strips:
            other_strip.mute = other_strip != strip
        modifier = strip.modifiers[config["effect"]]
        for later in list(strip.modifiers)[list(strip.modifiers).index(modifier) + 1:]:
            strip.modifiers.remove(later)
        modifier.mute = False
        modifier.enable = True
        tree = modifier.node_group.copy()
        modifier.node_group = tree
        render.use_sequencer = True
    elif context == "effect":
        effects = list(scene.compositor_effects)
        index = config["effect"]
        effect = effects[index]
        for later in effects[index + 1:]:
            later.enable_for_render = False
        effect.enable_for_render = True
        tree = effect.node_group.copy()
        effect.node_group = tree
        render.use_sequencer = False
    else:
        tree = scene.compositing_node_group.copy()
        scene.compositing_node_group = tree
        for effect in scene.compositor_effects:
            effect.enable_for_render = False
        render.use_sequencer = False

    target = tree.nodes[config["node"]]
    source_node = tree.nodes[config["source_node"]]
    source = next(socket for socket in source_node.outputs if socket.identifier == config["source_socket"])
    output = next((node for node in tree.nodes if node.type == "GROUP_OUTPUT" and node.is_active_output), None)
    if output is None or not output.inputs or output.inputs[0].type != "RGBA":
        raise ValueError("The compositor tree needs an active Group Output with Image as its first socket.")
    image_input = output.inputs[0]
    if context == "strip":
        # The Sequencer places the strip on the scene canvas using its existing
        # transforms. Shrinking that canvas first can cut off the strip.
        tree.links.new(source, output.inputs[0])
    else:
        scale = tree.nodes.new("CompositorNodeScale")
        scale.inputs["Type"].default_value = "Render Size"
        scale.inputs["Frame Type"].default_value = "Fit"
        tree.links.new(source, scale.inputs["Image"])
        tree.links.new(scale.outputs["Image"], output.inputs[0])
        image_input = scale.inputs["Image"]
    hint = config.get("hint")
    if hint:
        hint_node = tree.nodes[hint["node"]]
        hint_socket = next(socket for socket in hint_node.outputs if socket.identifier == hint["socket"])
        hint_value = tree.nodes.new("ShaderNodeMath")
        hint_value.operation = "MULTIPLY"
        hint_value.inputs[1].default_value = 1
        hint_value.use_clamp = True
        tree.links.new(hint_socket, hint_value.inputs[0])
    tree.nodes.remove(target)

    if context != "strip" and scene.camera is None:
        camera = bpy.data.objects.new("Bake camera", bpy.data.cameras.new("Bake camera"))
        scene.collection.objects.link(camera)
        scene.camera = camera

    render.use_compositing = True
    if context != "strip":
        render.resolution_x = config["width"]
        render.resolution_y = config["height"]
        render.resolution_percentage = 100
        render.pixel_aspect_x = render.pixel_aspect_y = 1
    render.use_stamp = False
    render.use_multiview = False
    render.dither_intensity = 0
    settings = render.image_settings
    # The project copy may be set to video, which only allows FFmpeg.
    settings.media_type = "IMAGE"
    settings.color_management = "OVERRIDE"
    color_space = config.get("linear_color_space")
    extension = set_plate_format(settings, color_space)

    destination = Path(config["destination"])
    destination.mkdir()
    first, last = config["first"], config["last"]
    quarter_turns = []
    for index, frame in enumerate(range(first, last + 1)):
        scene.frame_set(frame)
        if context == "strip":
            # Apply right-angle rotation before inference and undo it on the cutout.
            angle = strip.transform.rotation
            turns = round(angle / (math.pi / 2))
            quarter_turns.append(turns % 4 if math.isclose(angle, turns * math.pi / 2, abs_tol=1e-5) else 0)
            strip.transform.scale_x = strip.transform.scale_y = 1
            strip.transform.offset_x = strip.transform.offset_y = strip.transform.rotation = 0
            strip.crop.min_x = strip.crop.max_x = strip.crop.min_y = strip.crop.max_y = 0
        output_path = destination / f"{index:06d}{extension}"
        render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
        if hint and index == 0:
            tree.links.new(hint_value.outputs[0], image_input)
            set_png_format(settings, "Raw")
            render.filepath = hint["path"]
            bpy.ops.render.render(write_still=True, scene=scene.name)
            if not Path(hint["path"]).is_file():
                raise RuntimeError("Blender did not bake the first-frame matte hint.")
            set_plate_format(settings, color_space)
            tree.links.new(source, image_input)
        if context == "strip":
            strip.transform.rotation = angle
        if not output_path.is_file():
            raise RuntimeError(f"Blender did not bake frame {frame}.")
        print(f"Bake {index + 1}/{last - first + 1}", flush=True)
    if context == "strip":
        print("Fitting baked frames to model resolution", flush=True)
        subprocess.run([
            config["python"], "-I", str(Path(__file__).with_name("fit_bake.py")),
            str(destination), str(config["width"]), str(config["height"]),
            *([hint["path"]] if hint else []),
        ], input=json.dumps(quarter_turns), text=True, check=True)


if __name__ == "__main__":
    bake(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
