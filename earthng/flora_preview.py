"""Look at a converted flora shape without the game: its levels side by side, rendered by Blender.

    blender -b --factory-startup -P earthng/flora_preview.py -- <shape.dae> <out.png> [--wind] [--top]
    blender -b --factory-startup -P earthng/flora_preview.py -- --pack <pack folder> <out folder> --top

Blender (5.x has no Collada importer) is only the renderer here: the script reads the shape as
earthng/flora_mesh.py writes it (geometries lod0..n, one index a vertex, a triangle group a
material) and the materials beside it (main.materials.json: colour, opacity and normal maps), so
what is seen is what the game is given: the levels' geometry, the texture coordinates, the
cut-outs. --wind paints the wind colours instead (red flutter, green phase, blue sway).

It checks the files, not the game's shading: the frame is no proof of how a tree looks in BeamNG.
"""
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy

NS = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}


def read_shape(path):
    """[(node name, [(material, positions, normals, uvs, colours, faces)])] of the shape's levels."""
    root = ET.parse(path).getroot()
    geometries = {}
    for geometry in root.findall('.//c:geometry', NS):
        gid = geometry.get('id')

        def source(suffix, width):
            node = geometry.find(f".//c:source[@id='{gid}-{suffix}']/c:float_array", NS)
            if node is None or not node.text:
                return None
            values = [float(v) for v in node.text.split()]
            return [values[k:k + width] for k in range(0, len(values), width)]

        positions, normals, uvs, colours = source('pos', 3), source('nrm', 3), source('uv', 2), source('col', 4)
        groups = []
        for triangles in geometry.findall('.//c:triangles', NS):
            index = [int(v) for v in triangles.find('c:p', NS).text.split()]
            groups.append((triangles.get('material'), [index[k:k + 3] for k in range(0, len(index), 3)]))
        geometries[gid] = (positions, normals, uvs, colours, groups)
    levels = []
    for node in root.findall(".//c:node[@name='start01']/c:node", NS):
        inst = node.find('c:instance_geometry', NS)
        if inst is None or node.get('name', '').startswith('Colmesh'):
            continue
        levels.append((node.get('name'), geometries[inst.get('url').lstrip('#')]))
    return levels


def material_for(name, defs, folder, wind):
    material = bpy.data.materials.get(name)
    if material:
        return material
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    shader = tree.nodes.get('Principled BSDF')
    if wind:
        attribute = tree.nodes.new('ShaderNodeVertexColor')
        attribute.layer_name = 'wind'
        tree.links.new(attribute.outputs['Color'], shader.inputs['Emission Color'])
        shader.inputs['Emission Strength'].default_value = 1
        shader.inputs['Base Color'].default_value = (0, 0, 0, 1)
        return material
    definition = defs.get(name) or {}
    stage = (definition.get('Stages') or [{}])[0]
    shader.inputs['Roughness'].default_value = stage.get('roughnessFactor', .9)
    factor = stage.get('baseColorFactor')

    def image(key, colour):
        file = stage.get(key)
        if not file:
            return None
        node = tree.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(str(folder / Path(file).name))
        if not colour:
            node.image.colorspace_settings.name = 'Non-Color'
        return node

    base = image('baseColorMap', True)
    if base:
        tree.links.new(base.outputs['Color'], shader.inputs['Base Color'])
    elif factor:
        # the material's factor is sRGB, the shader's input linear
        shader.inputs['Base Color'].default_value = [((v + .055) / 1.055) ** 2.4 if v > .04045 else v / 12.92
                                                     for v in factor[:3]] + [1]
    opacity = image('opacityMap', False)
    if opacity and definition.get('alphaTest'):
        cut = tree.nodes.new('ShaderNodeMath')
        cut.operation = 'GREATER_THAN'
        cut.inputs[1].default_value = definition.get('alphaRef', 128) / 255
        tree.links.new(opacity.outputs['Color'], cut.inputs[0])
        tree.links.new(cut.outputs[0], shader.inputs['Alpha'])
        for field, value in (('surface_render_method', 'DITHERED'), ('blend_method', 'CLIP')):
            try:
                setattr(material, field, value)
            except (AttributeError, TypeError):
                pass
    material.use_backface_culling = not definition.get('doubleSided', False)
    return material


def build(levels, defs, folder, wind, gap=1.15):
    """The levels in a row along x; returns the row's box (min, max)."""
    low, high = [1e9] * 3, [-1e9] * 3
    widths = []
    for _, (positions, *_rest) in levels:
        xs = [p[0] for p in positions]
        widths.append((min(xs), max(xs)))
    span = max(b - a for a, b in widths)
    for index, (name, (positions, normals, uvs, colours, groups)) in enumerate(levels):
        shift = index * span * gap
        mesh = bpy.data.meshes.new(name)
        faces, slots = [], []
        for material, group in groups:
            slot = len(mesh.materials)
            mesh.materials.append(material_for(material, defs, folder, wind))
            faces += group
            slots += [slot] * len(group)
        mesh.from_pydata([(p[0] + shift, p[1], p[2]) for p in positions], [], faces)
        mesh.polygons.foreach_set('material_index', slots)
        layer = mesh.uv_layers.new(name='uv')
        colour = mesh.color_attributes.new('wind', 'FLOAT_COLOR', 'CORNER') if colours else None
        for polygon in mesh.polygons:
            for loop, vertex in zip(polygon.loop_indices, polygon.vertices):
                layer.data[loop].uv = uvs[vertex]
                if colour:
                    colour.data[loop].color = colours[vertex]
        if normals:
            try:
                mesh.normals_split_custom_set_from_vertices(normals)
            except (AttributeError, RuntimeError):
                pass
        mesh.update()
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(name, mesh))
        for p in positions:
            for k, v in enumerate((p[0] + shift, p[1], p[2])):
                low[k], high[k] = min(low[k], v), max(high[k], v)
    return low, high


def clear():
    """Nothing of the last shape (or of the factory scene: its cube, lamp and camera are not in
    the scene's own collection)."""
    for block in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)


def render(shape, out, wind=False, top=False):
    """One shape's levels side by side (top: its most detailed level alone, in a square frame)."""
    levels = read_shape(shape)
    if top:
        levels = levels[:1]
    file = shape.with_name('main.materials.json')
    defs = json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    scene = bpy.context.scene
    clear()
    low, high = build(levels, defs, shape.parent, wind)
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    wide, tall = high[0] - low[0], high[2] - low[2]
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = 'ORTHO'
    aspect = 1. if top else max(1., min(4., wide / max(.01, tall)))
    side = 640 if top else 900
    scene.render.resolution_x, scene.render.resolution_y = int(side * aspect), side
    camera.data.ortho_scale = max(wide, tall * aspect, .3) * 1.1
    camera.location = (centre[0], low[1] - 60, centre[2] + 60 * math.tan(math.radians(8)))
    camera.rotation_euler = (math.radians(82), 0, 0)
    camera.data.clip_end = 500
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.get('preview') or bpy.data.worlds.new('preview')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (.55, .68, .85, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = .9
    scene.world = world
    for engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT', 'BLENDER_WORKBENCH'):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.view_settings.view_transform = 'Standard'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print('rendered', out, [name for name, _ in levels], flush=True)


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    wind, top, pack = '--wind' in args, '--top' in args, '--pack' in args
    args = [a for a in args if not a.startswith('--')]
    source, out = Path(args[0]).resolve(), Path(args[1]).resolve()
    if not pack:
        render(source, out, wind, top)
        return
    # every shape of a pack's folder, a picture each (those already there are kept)
    out.mkdir(parents=True, exist_ok=True)
    for shape in sorted(source.rglob('*.dae')):
        target = out / f'{shape.stem}.png'
        if not target.exists():
            try:
                render(shape, target, wind, top)
            except Exception as error:      # one bad shape does not stop the sheet
                print('failed', shape.name, error, flush=True)


if __name__ == '__main__':
    main()
