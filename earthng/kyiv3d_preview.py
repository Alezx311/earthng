"""Blender background preview: blender -b -t 4 -P earthng/kyiv3d_preview.py -- asset.glb outdir.

Four labelled viewpoints make the asset's front and orientation reviewable before
placing it. This reads only the supplied generated mesh, never game assets.
"""
from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector


def main():
    source, target = sys.argv[sys.argv.index('--') + 1:]
    source, target = Path(source).resolve(), Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bounds = [o.matrix_world @ Vector(p) for o in meshes for p in o.bound_box]
    low = Vector(tuple(min(v[i] for v in bounds) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in bounds) for i in range(3)))
    centre = (low + high) * .5
    span = max(high - low)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 20
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.world.color = (.4, .4, .4)
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value = (.75, .79, .83, 1)
    scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .65
    scene.view_settings.view_transform = 'Standard'
    bpy.ops.object.light_add(type='AREA', location=centre + Vector((span, -span, span * 2)))
    bpy.context.object.data.energy = span * span * 300
    bpy.context.object.data.shape = 'DISK'
    bpy.context.object.data.size = span * 2
    bpy.context.object.rotation_euler = (centre - bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = span * 1.55
    scene.camera = camera
    for label, direction in [('south', (1, -2, 1.1)), ('north', (-1, 2, 1.1)),
                             ('east', (2, .7, 1.1)), ('west', (-2, -.7, 1.1))]:
        camera.location = centre + Vector(direction) * span
        camera.rotation_euler = (centre - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(target / f'{source.stem}-{label}.png')
        bpy.ops.render.render(write_still=True)
    print('PREVIEW', source.name, 'bounds', list(low), list(high), flush=True)


if __name__ == '__main__':
    main()
