"""Cut a bbox out of a country .osm.pbf into a .osm.pbf, with the selection of Earth2Road's
Earth2Road's OSM extraction (which writes OSM XML; rules in osm_select.py): every way with a node inside,
restriction/multipolygon/landmark relations with a member inside and their members, all nodes
of the selected ways, POI nodes inside. The input for earthng/osm_tiles.py.

    C:/js/Earth2Road/.venv/Scripts/python.exe earthng/osm_extract_pbf.py C:/js/Earth2Road/out/districts/.inputs/geofabrik/ukraine-260918.osm.pbf data/kyiv-oblast-260918.osm.pbf --bbox 29.2,49.15,32.2,51.6
"""
import argparse
from pathlib import Path
import sys
import time

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osm_select import drop_incomplete, landmark_category, poi  # noqa: E402


def extract(pbf, out, bbox):
    write(pbf, out, select(pbf, [bbox])[0])


def select(pbf, bboxes):
    """What extract() keeps for each of several boxes, from one read of pbf: a country is read
    once for all its extracts instead of once per extract (Ukraine: 8 reads of 9 minutes)."""
    boxes = [tuple(float(v) for v in b) for b in bboxes]
    full = (1 << len(boxes)) - 1
    t = time.monotonic()

    def mask(loc):
        if not loc.valid():
            return 0
        lon, lat = loc.lon, loc.lat
        m = 0
        for c, (w, s, e, n) in enumerate(boxes):
            if w <= lon <= e and s <= lat <= n:
                m |= 1 << c
        return m
    picks = [{'ways': set(), 'relations': set(), 'member_nodes': set(), 'inside_nodes': set()} for _ in boxes]
    relation_members, relevant = {}, set()
    processor = osmium.FileProcessor(str(pbf)).with_locations().with_filter(
        osmium.filter.EmptyTagFilter().enable_for(osmium.osm.NODE))
    for obj in processor:
        if obj.is_node():
            m = mask(obj.location)
            if m:
                keep = bool(obj.tags) and (poi(obj.tags) or landmark_category(obj.tags))
                for c in range(len(boxes)):
                    if m >> c & 1:
                        picks[c]['inside_nodes'].add(obj.id)
                        if keep:
                            picks[c]['member_nodes'].add(obj.id)
        elif obj.is_way():
            m = 0
            for nd in obj.nodes:
                m |= mask(nd.location)
                if m == full:
                    break
            if m:
                for c in range(len(boxes)):
                    if m >> c & 1:
                        picks[c]['ways'].add(obj.id)
        elif obj.is_relation():
            relation_members[obj.id] = [(m.type, m.ref) for m in obj.members]
            if obj.tags.get('type') in ('restriction', 'multipolygon') or landmark_category(obj.tags):
                relevant.add(obj.id)
                for member in obj.members:
                    if member.type == 'n':
                        try:
                            m = mask(processor.node_location_storage.get(member.ref))
                        except KeyError:
                            continue
                        for c in range(len(boxes)):
                            if m >> c & 1:
                                picks[c]['inside_nodes'].add(member.ref)
    out = []
    for pick in picks:
        ways, relations, member_nodes, inside_nodes = pick['ways'], pick['relations'], pick['member_nodes'], pick['inside_nodes']
        changed = True
        while changed:
            hits = {rid for rid, members in relation_members.items() if rid in relevant and any(
                (kind == 'w' and ref in ways) or (kind == 'n' and ref in inside_nodes)
                or (kind == 'r' and ref in relations) for kind, ref in members)}
            changed = bool(hits - relations)
            relations |= hits
        pending = list(relations)
        while pending:
            rid = pending.pop()
            for kind, ref in relation_members.get(rid, []):
                if kind == 'w':
                    ways.add(ref)
                elif kind == 'n':
                    member_nodes.add(ref)
                elif kind == 'r' and ref not in relations:
                    relations.add(ref)
                    pending.append(ref)
        out.append({'ways': ways, 'relations': relations, 'member_nodes': member_nodes,
                    'relation_members': {rid: relation_members[rid] for rid in relations if rid in relation_members}})
        del pick['inside_nodes']
    print(f'pass 1: {len(boxes)} extracts, ' + ', '.join(f"{len(o['ways'])} ways" for o in out)
          + f' ({time.monotonic()-t:.0f} s)', flush=True)
    return out


def write(pbf, out, pick):
    """The objects one select() pick names, from pbf into out (complete ways and relations)."""
    t = time.monotonic()
    ways, relations, relation_members = pick['ways'], pick['relations'], pick['relation_members']
    nodes = set(pick['member_nodes'])
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(ways)):
        nodes.update(nd.ref for nd in obj.nodes)
    print(f'pass 2: {len(nodes)} nodes ({time.monotonic()-t:.0f} s)', flush=True)
    out = Path(out)
    tmp = out.with_name(out.name + '.part.osm.pbf')
    tmp.parent.mkdir(parents=True, exist_ok=True)
    # Only relation members are checked for completeness: remembering every written node too
    # (22 M ids for a quarter of Ukraine) was the cut's memory peak.
    members = {'n': set(), 'w': set()}
    for rid in relations:
        for kind, ref in relation_members.get(rid, []):
            if kind in members:
                members[kind].add(ref)
    written = {'n': set(), 'w': set()}
    with osmium.SimpleWriter(osmium.io.File(str(tmp), 'pbf'), overwrite=True) as writer:
        for kind, key, ids, add in ((osmium.osm.NODE, 'n', nodes, writer.add_node), (osmium.osm.WAY, 'w', ways, writer.add_way)):
            wanted = members[key]
            for obj in osmium.FileProcessor(str(pbf), kind).with_filter(osmium.filter.IdFilter(ids)):
                add(obj)
                if obj.id in wanted:
                    written[key].add(obj.id)
        del nodes
        complete = drop_incomplete(relations, relation_members, written)
        if len(complete) < len(relations):
            print(f'left out {len(relations)-len(complete)} relations with members outside the package', flush=True)
        for obj in osmium.FileProcessor(str(pbf), osmium.osm.RELATION).with_filter(osmium.filter.IdFilter(complete)):
            writer.add_relation(obj)
    tmp.replace(out)
    print(f'written {out} ({time.monotonic()-t:.0f} s)', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('pbf'); p.add_argument('out')
    p.add_argument('--bbox', required=True, help='west,south,east,north')
    a = p.parse_args()
    extract(a.pbf, a.out, [float(v) for v in a.bbox.split(',')])
