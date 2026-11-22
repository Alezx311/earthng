"""A light physical pedestrian, our own, to take a walker's place (walkers.lua) just before a car hits
it (pedhit.lua; as handoff.lua does for flow cars). In the planet as vehicles/e2r_ped/ (vehicle_files).

Two kinds of body. Where the walkers are the fal figures (traffic_art.py), each figure has its own:
vehicles/e2r_<figure>/, the figure's own mesh and map in the pose of its walk's first step, its
nodes at the figure's joints (traffic_art.cook_body), so the walker struck is the same person a
moment later. Else, and in a planet without the fal models, the drawn mannequin e2r_ped painted in
the walker's colours.

A soft-body "vehicle" of 41 nodes: the standing pose of people_art.py as a node skeleton, its mesh cut
into body parts, each a flexbody on that part's own nodes (one flexbody over the whole skeleton tore into
slivers once the joints came loose, p16). A limb segment has two joint nodes and two light FIN nodes beside
its middle (one forward, one to the side), so every part has a tetrahedron of nodes that moves only with
it: a flexbody needs a node off the line of the other two ("VY node not found" with one fin).
It stands as a statue: the limbs are stiff beams, and the joints are held
by LOCK beams (diagonals across the hip, knee, ankle, shoulder and neck) that break at a moderate
force. A car breaks the locks and the body falls loose; nothing else (no controller, no brain).
Loose is not limp string, though: TISSUE beams across every joint, soft and heavily damped inside
their bounds and hard beyond them, keep a knee from folding forward and a head from turning
round, and take the swing out of the limbs, so the body drops and rolls as a weight and lies
still. The mass is a person's, shared as a person's (the trunk more than half), and the trunk and
the limbs have collision triangles, so a car's own nodes meet them: the car is what throws the
body, with no speed added by hand (pedhit.lua).
Shirt, pants and skin are the vehicle's paints 1-3 through the same palette masks as the fake walker,
so the swap keeps the colours.

Vehicle space: forward -y, up +z, origin on the ground between the feet (the fake walker's +x turned).

    .venv\\Scripts\\python.exe earthng\\ped_body.py <user>/current/vehicles/e2r_ped [lock N]

The game keeps a vehicle's shape in temp/vehicles/<model>/*.cdae and for the session: a changed mesh
under the same DAE name is not picked up in a running game (rename it while working on it).
"""
import json
import math
import sys
from pathlib import Path

import flow_art
import people_art as pa

MODEL = 'e2r_ped'
MASS = 70.0
# share of the mass by node (kg of a 69 kg body): pelvis 11, chest and belly 24, head and neck 5.7,
# a leg 10.5 (thigh 6.6 with its knee, shin 3, foot 0.9), an arm 3.6
WEIGHT = {'p': 2.75, 'c': 6.0, 'n': 1.0, 'hd': 3.5, 'hb': 1.2, 'k': 3.0, 'q': 1.8, 'a': 1.2, 's': .9, 't': .35,
          'h': .35, 'o': .2, 'e': 1.0, 'u': .6, 'w': .6, 'f': .4}


def weight(name):
    return WEIGHT[name] if name in WEIGHT else WEIGHT[name[0]]


def part_nodes():
    """Body parts (people_art.triangles parts) and the nodes each one's flexbody follows."""
    out = {'trunk': ['pl', 'pr', 'pf', 'pb', 'cl', 'cr', 'cf', 'cb', 'n'], 'head': ['n', 'hd', 'hb']}
    for t in 'lr':
        out['thigh_' + t] = ['p' + t, 'k' + t, 'q' + t, 'q' + t + 'x']
        out['shin_' + t] = ['k' + t, 'a' + t, 's' + t, 's' + t + 'x']
        out['foot_' + t] = ['a' + t, 't' + t, 'h' + t, 'o' + t]
        out['upper_' + t] = ['c' + t, 'e' + t, 'u' + t, 'u' + t + 'x']
        out['fore_' + t] = ['e' + t, 'w' + t, 'f' + t, 'f' + t + 'x']
    return out


def to_vehicle(p):
    """people_art space (forward +x) to vehicle space (forward -y)."""
    return (p[1], -p[0], p[2])


def skeleton():
    """Node name -> position (vehicle space) of the standing pose, by the same kinematics as the mesh."""
    nodes = {}
    legs = {1: (2, 4), -1: (-1, 3)}
    arms = {1: (4, 12), -1: (-3, 14)}
    for side, tag in ((1, 'l'), (-1, 'r')):
        hip, knee = legs[side]
        h = (0, side * pa.HIP_W, pa.HIP)
        k = pa._rot(hip, pa.THIGH, h)
        f = pa._rot(hip - knee, pa.SHIN, k)
        nodes['p' + tag] = h
        nodes['k' + tag] = k
        nodes['a' + tag] = (f[0], f[1], max(f[2], .08))
        nodes['t' + tag] = (f[0] + .15, f[1], .03)        # toe
        nodes['h' + tag] = (f[0] - .09, f[1], .03)        # heel
        shoulder, elbow = arms[side]
        s = (0, side * pa.SHOULDER_W, pa.SHOULDER)
        e = pa._rot(shoulder, pa.UPPER, s)
        w = pa._rot(shoulder + elbow, pa.FORE, e)
        nodes['c' + tag] = s
        nodes['e' + tag] = e
        nodes['w' + tag] = w
        mid = lambda a, b, dx, dy: ((a[0] + b[0]) / 2 + dx, (a[1] + b[1]) / 2 + dy, (a[2] + b[2]) / 2)
        nodes['q' + tag] = mid(h, k, .08, 0)               # fins: forward and outward of each segment
        nodes['q' + tag + 'x'] = mid(h, k, 0, side * .08)
        nodes['s' + tag] = mid(k, f, .10, 0)
        nodes['s' + tag + 'x'] = mid(k, f, 0, side * .10)
        nodes['u' + tag] = mid(s, e, 0, side * .07)
        nodes['u' + tag + 'x'] = mid(s, e, .07, 0)
        nodes['f' + tag] = mid(e, w, 0, side * .06)
        nodes['f' + tag + 'x'] = mid(e, w, .06, 0)
        nodes['o' + tag] = (f[0] + .03, f[1] + side * .06, .06)   # outer side of the foot
    nodes['pf'] = (.09, 0, pa.HIP + .04)
    nodes['pb'] = (-.09, 0, pa.HIP + .04)
    nodes['cf'] = (.11, 0, 1.25)
    nodes['cb'] = (-.11, 0, 1.25)
    nodes['n'] = (0, 0, pa.SHOULDER + .09)
    nodes['hd'] = (.01, 0, pa.SHOULDER + .23)
    nodes['hb'] = (-.09, 0, pa.SHOULDER + .19)          # back of the head: the head's third node
    return {name: to_vehicle(p) for name, p in nodes.items()}


# structural beams: segments and the closed boxes of pelvis, chest and feet
BONES = [
    ('pl', 'pr'), ('pl', 'pf'), ('pl', 'pb'), ('pr', 'pf'), ('pr', 'pb'), ('pf', 'pb'),
    ('cl', 'cr'), ('cl', 'cf'), ('cl', 'cb'), ('cr', 'cf'), ('cr', 'cb'), ('cf', 'cb'),
    ('pf', 'cf'), ('pb', 'cb'), ('pl', 'cl'), ('pr', 'cr'), ('pf', 'cb'), ('pb', 'cf'),
    ('pl', 'cf'), ('pr', 'cb'),
    ('cl', 'n'), ('cr', 'n'), ('cf', 'n'), ('cb', 'n'), ('n', 'hd'), ('n', 'hb'), ('hd', 'hb'),
]
for t in 'lr':
    BONES += [('p' + t, 'k' + t), ('k' + t, 'a' + t), ('a' + t, 't' + t), ('a' + t, 'h' + t), ('t' + t, 'h' + t),
              ('c' + t, 'e' + t), ('e' + t, 'w' + t),
              ('a' + t, 'o' + t), ('t' + t, 'o' + t), ('h' + t, 'o' + t)]
    for j0, j1, fin in (('p', 'k', 'q'), ('k', 'a', 's'), ('c', 'e', 'u'), ('e', 'w', 'f')):
        x = fin + t + 'x'
        BONES += [(j0 + t, fin + t), (j1 + t, fin + t), (j0 + t, x), (j1 + t, x), (fin + t, x)]
# locks: the joints held straight until a hit breaks them
LOCKS = [('cf', 'hd'), ('cb', 'hd'), ('cl', 'hd'), ('cr', 'hd'), ('cb', 'hb')]
for t in 'lr':
    LOCKS += [('pf', 'k' + t), ('pb', 'k' + t), ('p' + ('r' if t == 'l' else 'l'), 'k' + t),   # hip
              ('p' + t, 'a' + t),                                                             # knee
              ('k' + t, 't' + t), ('k' + t, 'h' + t),                                         # ankle
              ('cf', 'e' + t), ('cb', 'e' + t), ('p' + t, 'e' + t),                           # shoulder
              ('c' + t, 'w' + t)]                                                             # elbow
# out of the leg's plane: hip, knee and ankle are near one line and the foot is flat, so without these the
# knees fold sideways and the statue sinks over in ~1.2 s (p15): the feet tied into one base, ankles and
# wrists crossed to the other side
LOCKS += [('tl', 'tr'), ('hl', 'hr'), ('tl', 'hr'), ('hl', 'tr'),
          ('al', 'pr'), ('ar', 'pl'), ('al', 'kr'), ('ar', 'kl'),
          ('cf', 'wl'), ('cb', 'wl'), ('cf', 'wr'), ('cb', 'wr')]
# long stays from the torso to the feet: the frame of a statue (they are what a hit snaps first)
for t in 'lr':
    LOCKS += [('cf', 't' + t), ('cb', 'h' + t), ('c' + t, 't' + t), ('c' + t, 'h' + t), ('pf', 't' + t), ('pb', 'h' + t)]
# a fin turns freely round its segment: held until the hit, so the limb does not twist while standing
for t in 'lr':
    LOCKS += [('q' + t, 'pf'), ('s' + t, 't' + t), ('u' + t, 'cf'), ('f' + t, 'cf')]


# Tissue: what holds a joint once its locks are broken. Each is a beam between two nodes no bone or
# lock joins, soft and heavily damped while its length stays within (short, long) of its length at
# rest (shares of it), hard beyond. (pair, short, long):
TISSUE = [(('cf', 'hb'), .25, .2), (('cl', 'hb'), .25, .25), (('cr', 'hb'), .25, .25),      # the neck
          (('qlx', 'qrx'), .55, 1.3)]                                                         # the legs apart
for t in 'lr':
    TISSUE += [(('q' + t, 's' + t), .5, .04),         # knee: folds back, does not fold forward
               (('cf', 'q' + t), .6, .1),             # hip: the thigh up to the chest, a little way back
               (('s' + t, 'o' + t), .3, .2),          # ankle
               (('cb', 'u' + t), .6, .8),             # shoulder
               (('n', 'u' + t + 'x'), .7, .9),
               (('u' + t + 'x', 'f' + t + 'x'), .6, .06)]   # elbow


def collision_triangles(nodes):
    """The body's faces a car's nodes can meet: the trunk's hull, a tetrahedron a limb segment and a
    foot. Each is wound so that it faces away from the middle of its solid."""
    solids = [['pf', 'pl', 'pb', 'pr', 'cf', 'cl', 'cb', 'cr', 'n']]
    faces = [[('pf', 'pl', 'cl'), ('pf', 'cl', 'cf'), ('pl', 'pb', 'cb'), ('pl', 'cb', 'cl'), ('pb', 'pr', 'cr'),
              ('pb', 'cr', 'cb'), ('pr', 'pf', 'cf'), ('pr', 'cf', 'cr'), ('cf', 'cl', 'n'), ('cl', 'cb', 'n'),
              ('cb', 'cr', 'n'), ('cr', 'cf', 'n'), ('pf', 'pb', 'pl'), ('pf', 'pr', 'pb')]]
    for t in 'lr':
        for a, b, c, d in (('p', 'k', 'q', 'q@x'), ('k', 'a', 's', 's@x'), ('c', 'e', 'u', 'u@x'), ('e', 'w', 'f', 'f@x'),
                           ('a', 't', 'h', 'o')):
            four = [(n[0] + t + 'x') if n.endswith('@x') else n + t for n in (a, b, c, d)]
            solids.append(four)
            faces.append([(four[0], four[1], four[2]), (four[0], four[1], four[3]), (four[0], four[2], four[3]),
                          (four[1], four[2], four[3])])
    out = []
    for solid, tris in zip(solids, faces):
        mid = [sum(nodes[n][i] for n in solid) / len(solid) for i in range(3)]
        for a, b, c in tris:
            pa, pb, pc = nodes[a], nodes[b], nodes[c]
            u = [pb[i] - pa[i] for i in range(3)]
            v = [pc[i] - pa[i] for i in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            away = sum(n[i] * ((pa[i] + pb[i] + pc[i]) / 3 - mid[i]) for i in range(3))
            out.append([a, b, c] if away >= 0 else [a, c, b])
    return out


def jbeam(nodes, lock_strength, model=MODEL, mass=MASS, name='EarthNG pedestrian'):
    total = sum(weight(name) for name in nodes)
    rows = [['id', 'posX', 'posY', 'posZ']]
    # (clothes on paint and on asphalt slide: with the grip of rubber a body stayed draped over the
    # bonnet of a car braking to a stand, hit-c1)
    rows.append({'collision': True, 'selfCollision': False, 'frictionCoef': .62, 'nodeMaterial': '|NM_RUBBER'})
    groups = {}
    for part, names in part_nodes().items():
        for node in names:
            groups.setdefault(node, []).append(f'{model}_{part}')
    for node, p in nodes.items():
        w = weight(node) / total * mass
        rows.append({'nodeWeight': round(w, 3), 'group': groups.get(node, '')})
        rows.append([node, *(round(x, 4) for x in p)])
    beams = [['id1:', 'id2:']]
    beams.append({'beamType': '|NORMAL', 'beamSpring': 300000, 'beamDamp': 90, 'beamDeform': 1.0e9,
                  'beamStrength': 'FLT_MAX', 'deformLimitExpansion': ''})
    beams += [list(b) for b in BONES]
    beams.append({'beamSpring': 300000, 'beamDamp': 90, 'beamDeform': lock_strength * .7,
                  'beamStrength': lock_strength})
    beams += [list(b) for b in LOCKS]
    for pair, short, long in TISSUE:
        beams.append({'beamType': '|BOUNDED', 'beamSpring': TISSUE_SPRING, 'beamDamp': TISSUE_DAMP,
                      'beamLimitSpring': 120000, 'beamLimitDamp': 600, 'beamShortBound': short, 'beamLongBound': long,
                      'beamDeform': 1.0e9, 'beamStrength': 'FLT_MAX'})
        beams.append(list(pair))
    tris = [['id1:', 'id2:', 'id3:'], {'dragCoef': 0, 'liftCoef': 0}] + collision_triangles(nodes)
    return {model: {
        'information': {'name': name, 'authors': 'EarthNG'},
        'slotType': 'main',
        'refNodes': [['ref:', 'back:', 'left:', 'up:'], ['pf', 'pb', 'pl', 'cf']],
        'nodes': rows,
        'beams': beams,
        'triangles': tris,
        'flexbodies': [['mesh', '[group]:', 'nonFlexMaterials']] + [[f'{model}_{part}', [f'{model}_{part}']]
                                                                     for part in part_nodes()],
        'paints': [],
    }}


TISSUE_SPRING, TISSUE_DAMP = 1500, 260


def body_dae():
    """The standing mesh in vehicle space, one mesh node per body part, named for its flexbody."""
    parts = {}
    pa.triangles(None, parts)
    mat = lambda m: f'{pa.PREFIX}v_{m}'
    fmt = lambda rows: ' '.join(f'{x:.4f}' for row in rows for x in row)
    acc = lambda src, n: (f'<technique_common><accessor source="#{src}" count="{n}" stride="3"><param name="X" type="float"/>'
                          '<param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>')
    used, geoms, scene = set(), [], []
    for part, tris in parts.items():
        name = f'{MODEL}_{part}'
        faces_by = {}
        for m, face in tris:
            faces_by.setdefault(m, []).append([to_vehicle(p) for p in face])
        pos, nrm, prims = [], [], []
        for m, faces in faces_by.items():
            used.add(m)
            idx = []
            for face, corners in zip(faces, flow_art._smooth(faces)):
                for p, n in zip(face, corners):
                    pos.append(p)
                    nrm.append(n)
                    idx += [len(pos) - 1, len(nrm) - 1]
            prims.append(f'<triangles material="{mat(m)}" count="{len(faces)}">'
                         f'<input semantic="VERTEX" source="#{name}-vtx" offset="0"/>'
                         f'<input semantic="NORMAL" source="#{name}-nrm" offset="1"/><p>{" ".join(map(str, idx))}</p></triangles>')
        geoms.append(f'<geometry id="{name}-g" name="{name}"><mesh>'
                     f'<source id="{name}-pos"><float_array id="{name}-pa" count="{3 * len(pos)}">{fmt(pos)}</float_array>'
                     f'{acc(name + "-pa", len(pos))}</source>'
                     f'<source id="{name}-nrm"><float_array id="{name}-na" count="{3 * len(nrm)}">{fmt(nrm)}</float_array>'
                     f'{acc(name + "-na", len(nrm))}</source>'
                     f'<vertices id="{name}-vtx"><input semantic="POSITION" source="#{name}-pos"/></vertices>'
                     f'{"".join(prims)}</mesh></geometry>')
        binds = ''.join(f'<instance_material symbol="{mat(m)}" target="#{mat(m)}"/>' for m in faces_by)
        scene.append(f'<node id="{name}" name="{name}"><instance_geometry url="#{name}-g"><bind_material>'
                     f'<technique_common>{binds}</technique_common></bind_material></instance_geometry></node>')
    effects = ''.join(f'<effect id="{mat(m)}-fx"><profile_COMMON><technique sid="common"><lambert><diffuse>'
                      f'<color>0.5 0.5 0.5 1</color></diffuse></lambert></technique></profile_COMMON></effect>'
                      for m in sorted(used))
    materials = ''.join(f'<material id="{mat(m)}" name="{mat(m)}"><instance_effect url="#{mat(m)}-fx"/></material>'
                        for m in sorted(used))
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
            '<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
            f'<library_effects>{effects}</library_effects><library_materials>{materials}</library_materials>'
            f'<library_geometries>{"".join(geoms)}</library_geometries>'
            f'<library_visual_scenes><visual_scene id="Scene">{"".join(scene)}</visual_scene></library_visual_scenes>'
            '<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>\n')


def materials():
    """The walker's materials for a vehicle: the palette masks take the vehicle's paints 1-3."""
    out = {}
    for m, stage in pa.MATERIALS.items():
        if m == 'blood':
            continue
        out[pa.PREFIX + 'v_' + m] = {'name': pa.PREFIX + 'v_' + m, 'mapTo': pa.PREFIX + 'v_' + m, 'class': 'Material',
                                     'version': 1.5, 'Stages': [dict(stage), {}, {}, {}]}
    return out


def files(lock_strength=1500):   # p17: 1500 N gives a loose body at 30-50 km/h, 4000 a plank
    nodes = skeleton()
    return {
        f'{MODEL}.jbeam': json.dumps(jbeam(nodes, lock_strength), indent=1),
        f'{MODEL}.dae': body_dae(),
        'main.materials.json': json.dumps(materials(), indent=2),
        'info.json': json.dumps({'Name': 'EarthNG pedestrian', 'Brand': 'EarthNG', 'Type': 'Prop',
                                 'default_pc': 'base', 'Author': 'EarthNG'}, indent=2),
        'base.pc': json.dumps({'format': 2, 'model': MODEL, 'parts': {}, 'vars': {}}, indent=2),
    }


def figure_files(lock_strength=1500):
    """The bodies of the fal figures (traffic_art.cook_body), a vehicle each: {path in the planet:
    text or bytes}. {} without the cooked models."""
    import traffic_art
    out = traffic_art.cooked()
    index = out / 'models.json'
    if not index.is_file():
        return {}
    result = {}
    for ped in json.loads(index.read_text(encoding='utf8'))['peds']:
        body = ped.get('body')
        if not body:
            continue
        model, root = body['model'], f'vehicles/{body["model"]}/'
        nodes = {name: tuple(p) for name, p in body['nodes'].items()}
        result[root + f'{model}.jbeam'] = json.dumps(jbeam(nodes, lock_strength, model, body['mass'],
                                                           f'EarthNG pedestrian {ped["name"]}'), indent=1)
        result[root + f'{model}.dae'] = (out / traffic_art.BODY_DIR / body['dae']).read_bytes()
        picture = out / traffic_art.PEOPLE_DIR / (ped['name'] + '.color.png')
        packed = picture.with_suffix('.dds') if picture.with_suffix('.dds').is_file() else picture
        result[root + packed.name] = packed.read_bytes()
        label = body['material']
        result[root + 'main.materials.json'] = json.dumps({label: {
            'name': label, 'mapTo': label, 'class': 'Material', 'version': 1.5,
            'Stages': [{'baseColorMap': f'/{root}{picture.name}', 'roughnessFactor': .86}, {}, {}, {}]}}, indent=1)
        result[root + 'info.json'] = json.dumps({'Name': f'EarthNG pedestrian {ped["name"]}', 'Brand': 'EarthNG',
                                                 'Type': 'Prop', 'default_pc': 'base', 'Author': 'EarthNG'}, indent=2)
        result[root + 'base.pc'] = json.dumps({'format': 2, 'model': model, 'parts': {}, 'vars': {}}, indent=2)
    return result


def vehicle_files():
    """The bodies for the planet ZIP (build_mod.py): the mannequin and the figures' own."""
    return {**{f'vehicles/{MODEL}/{name}': text for name, text in files().items()}, **figure_files()}


if __name__ == '__main__':
    target = Path(sys.argv[1])
    strength = float(sys.argv[2]) if len(sys.argv) > 2 else 1500
    target.mkdir(parents=True, exist_ok=True)
    for name, text in files(strength).items():
        (target / name).write_text(text, encoding='utf8')
    print(len(skeleton()), 'nodes', len(BONES), 'bones', len(LOCKS), 'locks')
