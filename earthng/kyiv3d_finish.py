"""Native fascia, roof repairs and collision proxies for generated Kyiv pavilions.

This is an offline authoring step: no model requests, keys, game processes or source
textures are touched. Re-running it replaces only this script's own additions.
"""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from fal_mesh import NS, Primitive, collada


FONT = Path('C:/Windows/Fonts/arialbd.ttf')
N = {'c': NS}


def _tag(name):
    return f'{{{NS}}}{name}'


def _colour(value):
    if isinstance(value, str):
        return tuple(ImageColor.getrgb(value))[:3]
    rgb = tuple(value)[:3]
    if len(rgb) != 3 or any(not isinstance(v, (int, float)) or not 0 <= v <= 255 for v in rgb):
        raise ValueError('Colours must be RGB bytes or a CSS/hex colour string')
    return tuple(round(v) for v in rgb)


def _library(root, name):
    found = root.find(f'c:{name}', N)
    if found is None:
        order = ['asset', 'library_images', 'library_effects', 'library_materials', 'library_geometries',
                 'library_controllers', 'library_visual_scenes', 'scene']
        found = ET.Element(_tag(name))
        target = order.index(name)
        index = next((i for i, node in enumerate(root) if node.tag.split('}')[-1] in order and
                      order.index(node.tag.split('}')[-1]) > target), len(root))
        root.insert(index, found)
    return found


def _remove_owned(root, prefix):
    for parent in list(root.iter()):
        for child in list(parent):
            if child.get('id', '').startswith(prefix):
                parent.remove(child)


def _positions(root):
    arrays = []
    for geometry in root.findall('c:library_geometries/c:geometry', N):
        mesh = geometry.find('c:mesh', N)
        if mesh is None:
            continue
        for vertex_input in mesh.findall('c:vertices/c:input', N):
            if vertex_input.get('semantic') != 'POSITION':
                continue
            sid = vertex_input.get('source', '').removeprefix('#')
            source = mesh.find(f'c:source[@id="{sid}"]', N)
            if source is None:
                raise ValueError('DAE position source is missing')
            floats = source.find('c:float_array', N)
            accessor = source.find('c:technique_common/c:accessor', N)
            if floats is None or accessor is None:
                raise ValueError('DAE position accessor is incomplete')
            values = np.fromstring(floats.text or '', sep=' ')
            count, stride = int(accessor.get('count')), int(accessor.get('stride', 1))
            offset = int(accessor.get('offset', 0))
            if stride < 3 or len(values) < offset + count*stride:
                raise ValueError('DAE position accessor is truncated')
            arrays.append(values[offset:offset+count*stride].reshape(count, stride)[:, :3])
    if not arrays:
        raise ValueError('DAE has no position geometry')
    positions = np.concatenate(arrays)
    if not np.isfinite(positions).all():
        raise ValueError('DAE contains non-finite positions')
    return positions


def _box(x0, x1, y0, y1, z0, z1, material):
    corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)
    centre = corners.mean(axis=0)
    positions, normals, faces = [], [], []
    for indices in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                    (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        points = corners[list(indices)]
        normal = np.cross(points[1]-points[0], points[2]-points[0])
        if np.dot(normal, points.mean(axis=0)-centre) < 0:
            points = points[[0, 3, 2, 1]]
            normal = -normal
        normal /= np.linalg.norm(normal)
        k = len(positions)
        positions.extend(points)
        normals.extend([normal] * 4)
        faces.extend([[k, k+1, k+2], [k, k+2, k+3]])
    return Primitive(np.array(positions), np.array(normals), None, np.array(faces), material)


def _label_image(path, label, bg, fg, width_m, height_m):
    if not FONT.is_file():
        raise FileNotFoundError(f'Ukrainian fascia font is missing: {FONT}')
    width = 2048 if width_m > 2.5 else 1600
    height = max(256, min(512, round(width * height_m / width_m)))
    image = Image.new('RGB', (width, height), bg)
    draw = ImageDraw.Draw(image)
    font_size = round(height*.76)
    while font_size > 8:
        font = ImageFont.truetype(str(FONT), font_size)
        box = draw.textbbox((0, 0), label, font=font)
        if box[2]-box[0] <= width*.9 and box[3]-box[1] <= height*.78:
            break
        font_size -= 2
    x = (width-(box[2]-box[0]))/2-box[0]
    y = (height-(box[3]-box[1]))/2-box[1]
    draw.text((x, y), label, font=font, fill=fg)
    image.save(path)
    return [width, height]


def _material(name, colour, texture=None):
    stage = {'baseColorFactor': [v/255 for v in colour] + [1], 'roughnessFactor': .72, 'metallicFactor': 0}
    if texture:
        stage.update(baseColorMap=texture, baseColorFactor=[1, 1, 1, 1])
    return {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5, 'Stages': [stage, {}, {}, {}]}


def _prefix_ids(root, prefix):
    mapping = {node.get('id'): node.get('id') if node.get('id').startswith(prefix) else prefix+node.get('id')
               for node in root.iter() if node.get('id')}
    for node in root.iter():
        if node.get('id'):
            node.set('id', mapping[node.get('id')])
        for key, value in list(node.attrib.items()):
            if value.startswith('#') and value[1:] in mapping:
                node.set(key, '#'+mapping[value[1:]])


def finish(out, name, size, label, bg, fg, roof=None, collision=True):
    """Add readable Ukrainian signage and an optional roof/collision box to one DAE.

    ``roof`` is an RGB byte tuple / colour string, or ``{'colour': ..., 'thickness': .04}``.
    The source GLB's measured triangle/vertex counts remain unchanged in mesh.json.
    """
    out = Path(out)
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name) or not label.strip():
        raise ValueError('A safe asset slug and a nonempty label are required')
    dimensions = np.asarray(size, dtype=float)
    if dimensions.shape != (3,) or not np.isfinite(dimensions).all() or np.any(dimensions <= 0):
        raise ValueError('Size must have three positive finite metric dimensions')
    width, depth, height = dimensions
    if height < 1.5:
        raise ValueError('Pavilion fascia requires an asset at least 1.5 m high')
    bg, fg = _colour(bg), _colour(fg)
    prefix = f'e2r_kyiv3d_finish_{name}_'
    dae_path, materials_path, mesh_path = out/f'{name}.dae', out/'main.materials.json', out/'mesh.json'
    root = ET.parse(dae_path).getroot()
    if root.findtext('c:asset/c:up_axis', namespaces=N) != 'Z_UP':
        raise ValueError('Finishing expects a baked Z_UP DAE')
    unit = root.find('c:asset/c:unit', N)
    if unit is None or float(unit.get('meter', '0')) != 1:
        raise ValueError('Finishing expects metre units')
    _remove_owned(root, prefix)
    positions = _positions(root)
    band = positions[(positions[:, 2] >= height-.85) & (positions[:, 2] <= height-.35)]
    front_y = float(np.percentile((band if len(band) else positions)[:, 1], 5))-.025
    label_width = width*(.65 if name == 'coffee' else .7)
    label_height = max(.35, min(.45, height*.13))
    centre_z = height-.59
    z0, z1 = centre_z-label_height/2, centre_z+label_height/2
    vfs_root = f'/art/shapes/earthng/kyiv3d/{name}'
    png_name = prefix+'label.color.png'
    resolution = _label_image(out/png_name, label, bg, fg, label_width, label_height)
    labels = {0: prefix+'backing', 1: prefix+'label'}
    # The solid backing hides generated pseudo-lettering behind the clean sign.
    panel = _box(-width*.47, width*.47, front_y+.003, front_y+.033,
                 z0-.07, z1+.07, 0)
    label_positions = np.array([[-label_width/2, front_y, z0], [label_width/2, front_y, z0],
                                [label_width/2, front_y, z1], [-label_width/2, front_y, z1]])
    sign = Primitive(label_positions, np.tile([0., -1, 0], (4, 1)),
                     np.array([[0., 0], [1, 0], [1, 1], [0, 1]]), np.array([[0, 1, 2], [0, 2, 3]]), 1)
    primitives, roles = [panel, sign], ['backing', 'label']
    material_data = json.loads(materials_path.read_text(encoding='utf8'))
    material_data = {key: value for key, value in material_data.items() if not key.startswith(prefix)}
    own_materials = {labels[0]: _material(labels[0], bg),
                     labels[1]: _material(labels[1], bg, f'{vfs_root}/{png_name}')}
    roof_info = None
    if roof is not None and roof is not False:
        config = roof if isinstance(roof, dict) else {'colour': roof}
        colour = _colour(config.get('colour', config.get('color', '#45484b')))
        thickness = float(config.get('thickness', .04))
        if not np.isfinite(thickness) or not .005 <= thickness <= .15:
            raise ValueError('Roof cap thickness must be .005..15 m')
        material_index = len(labels)
        labels[material_index] = prefix+'roof'
        primitives.append(_box(-width/2, width/2, -depth/2, depth/2, height-thickness+.008, height+.008, material_index))
        roles.append('roof')
        own_materials[labels[material_index]] = _material(labels[material_index], colour)
        roof_info = {'colour': list(colour), 'thickness': thickness, 'top': height+.008}
    if collision:
        if any(node.get('name') == 'Colmesh-1' for node in root.findall('.//c:node', N)):
            raise ValueError('Source DAE already has a collision mesh; do not replace it implicitly')
        material_index = len(labels)
        labels[material_index] = prefix+'collision'
        primitives.append(_box(-width/2, width/2, -depth/2, depth/2, 0, height, material_index))
        roles.append('collision')
        own_materials[labels[material_index]] = _material(labels[material_index], (128, 128, 128))
    addition = ET.fromstring(collada(primitives, labels, prefix+'shape'))
    _prefix_ids(addition, prefix)
    # Also declare the sign texture in Collada, so independent DAE viewers can
    # display it and verify UV orientation before the game loads the PBR override.
    images = _library(addition, 'library_images')
    image_id = prefix+'label_image'
    image = ET.SubElement(images, _tag('image'), id=image_id, name=image_id)
    ET.SubElement(image, _tag('init_from')).text = png_name
    effect = addition.find(f'c:library_effects/c:effect[@id="{labels[1]}-fx"]', N)
    profile = effect.find('c:profile_COMMON', N)
    surface_id, sampler_id = prefix+'surface', prefix+'sampler'
    parameter = ET.Element(_tag('newparam'), sid=surface_id)
    surface = ET.SubElement(parameter, _tag('surface'), type='2D')
    ET.SubElement(surface, _tag('init_from')).text = image_id
    profile.insert(0, parameter)
    parameter = ET.Element(_tag('newparam'), sid=sampler_id)
    sampler = ET.SubElement(parameter, _tag('sampler2D'))
    ET.SubElement(sampler, _tag('source')).text = surface_id
    profile.insert(1, parameter)
    diffuse = profile.find('c:technique/c:lambert/c:diffuse', N)
    diffuse.clear()
    ET.SubElement(diffuse, _tag('texture'), texture=sampler_id, texcoord='UVMap')
    for library_name in ('library_images', 'library_effects', 'library_materials', 'library_geometries'):
        target = _library(root, library_name)
        target.extend(list(addition.find(f'c:{library_name}', N)))
    original_base = root.find('.//c:visual_scene/c:node[@name="base00"]', N)
    if original_base is None:
        raise ValueError('DAE lacks the expected base00 scene node')
    original_start = original_base.find('c:node[@name="start01"]', N)
    if original_start is None:
        raise ValueError('DAE lacks the expected start01 object node')
    added_start = addition.find('.//c:visual_scene/c:node/c:node', N)
    for node, role in zip(list(added_start), roles):
        node.set('id', prefix+role+'_node')
        node.set('name', 'Colmesh-1' if role == 'collision' else prefix+role+'_a100')
        original_start.append(node)
    if collision:
        ET.SubElement(original_base, _tag('node'), id=prefix+'collision_detail', name='collision-1')
    ET.register_namespace('', NS)
    dae_path.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    material_data.update(own_materials)
    materials_path.write_text(json.dumps(material_data, ensure_ascii=False, indent=2), encoding='utf8')
    metadata = json.loads(mesh_path.read_text(encoding='utf8'))
    render = [p for p, role in zip(primitives, roles) if role != 'collision']
    render_triangles = sum(len(p.faces) for p in render)
    rendered_positions = np.concatenate([positions]+[p.positions for p in render])
    metadata['finishing'] = {'version': 1, 'label': label, 'label_texture': f'{vfs_root}/{png_name}',
        'texture_resolution': resolution, 'front_y': front_y, 'label_width': label_width,
        'label_height': label_height, 'label_z': [z0, z1], 'roof_cap': roof_info,
        'render_triangles_added': render_triangles, 'collision_triangles': 12 if collision else 0,
        'collision_proxy': {'node': 'Colmesh-1', 'detail': 'collision-1',
                            'bounds': [[-width/2, -depth/2, 0], [width/2, depth/2, height]]} if collision else None}
    metadata['render_triangles_with_finish'] = metadata['triangles']+render_triangles
    metadata['finished_bounds'] = [rendered_positions.min(axis=0).tolist(), rendered_positions.max(axis=0).tolist()]
    mesh_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf8')
    return metadata['finishing']


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--size', required=True, help='X,Y,Z in metres')
    parser.add_argument('--label', required=True)
    parser.add_argument('--bg', default='#383a3c')
    parser.add_argument('--fg', default='#f4f1e9')
    parser.add_argument('--roof', help='optional solid roof cap colour')
    parser.add_argument('--no-collision', action='store_true')
    args = parser.parse_args()
    print(json.dumps(finish(args.out, args.name, [float(v) for v in args.size.split(',')], args.label,
                            args.bg, args.fg, args.roof, not args.no_collision), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
