"""Decode two EMC1/EMC2 canonical encodings (bridge_codec.lua) and print where they differ.

    .venv/Scripts/python.exe research/native-bridge/emc_diff.py a.emc b.emc [--limit 40]
"""
import argparse
import struct
import sys


def decode(data):
    magic = data[:4]
    assert magic in (b'EMC1', b'EMC2'), magic
    ops_n, nums_n, str_n, str_bytes, blob_n, blob_bytes = struct.unpack_from('<6I', data, 4)
    align = (lambda n: n + (-n) % 8) if magic == b'EMC2' else (lambda n: n)
    pos = 32 if magic == b'EMC2' else 28
    ops = struct.unpack_from(f'<{ops_n}i', data, pos); pos = align(pos + 4 * ops_n)
    nums = struct.unpack_from(f'<{nums_n}d', data, pos); pos += 8 * nums_n
    ends = struct.unpack_from(f'<{str_n}I', data, pos); pos += 4 * str_n
    sb = data[pos:pos + str_bytes]; pos = align(pos + str_bytes)
    bmarks = struct.unpack_from(f'<{blob_n}I', data, pos); pos = align(pos + 4 * blob_n)
    bb = data[pos:pos + blob_bytes]
    strs, last = [], 0
    for e in ends:
        strs.append(sb[last:e]); last = e
    if magic == b'EMC2':   # starts; each blob runs to the next start (padding is harmless: counts are in ops)
        blobs = [bb[s0:(bmarks[k + 1] if k + 1 < blob_n else len(bb))] for k, s0 in enumerate(bmarks)]
    else:                  # ends
        blobs, last = [], 0
        for e in bmarks:
            blobs.append(bb[last:e]); last = e
    st = {'op': 0, 'num': 0, 'str': 0, 'blob': 0}
    tables = []

    def op():
        v = ops[st['op']]; st['op'] += 1; return v

    def val():
        o = op()
        if o == 0: return None
        if o == 1: return False
        if o == 2: return True
        if o == 3:
            v = nums[st['num']]; st['num'] += 1; return v
        if o == 4: return op()
        if o == 5:
            return strs[op()].decode('utf8', 'replace')
        if o == 6:
            narr, nhash = op(), op()
            t = {}
            tables.append(t)
            for k in range(1, narr + 1):
                t[k] = val()
            for _ in range(nhash):
                k = val()
                if isinstance(k, float) and k.is_integer():
                    k = int(k)
                elif isinstance(k, (dict, list)):
                    k = 'tablekey:' + short(k)
                elif isinstance(k, tuple):
                    k = 'cdatakey:' + short(k)
                t[k] = val()
            return t
        if o == 7: return ('REF', op())
        if o == 8:
            typ, count = op(), op()
            b = blobs[op()]
            fmt = {1: 'ddd', 2: 'iii', 3: 'dd'}[typ]
            size = struct.calcsize('<' + fmt)
            return ('ARR', typ, [struct.unpack_from('<' + fmt, b, k * size) for k in range(count)])
        if o == 9:
            typ = op()
            b = blobs[op()]
            return ('ONE', typ, struct.unpack_from('<' + {1: 'ddd', 2: 'iii', 3: 'dd'}[typ], b, 0))
        raise ValueError(f'op {o} at {st["op"]}')
    return val()


def walk(a, b, path, out, limit):
    if len(out) >= limit:
        return
    if type(a) != type(b):
        out.append(f'{path}: type {type(a).__name__} vs {type(b).__name__}: {short(a)} | {short(b)}')
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append(f'{path}.{k}: only in B: {short(b[k])}')
            elif k not in b:
                out.append(f'{path}.{k}: only in A: {short(a[k])}')
            else:
                walk(a[k], b[k], f'{path}.{k}', out, limit)
            if len(out) >= limit:
                return
    elif isinstance(a, tuple) and a and a[0] == 'ARR':
        if a[1] != b[1] or len(a[2]) != len(b[2]):
            out.append(f'{path}: array type/len {a[1]}/{len(a[2])} vs {b[1]}/{len(b[2])}')
            return
        bad = [k for k in range(len(a[2])) if a[2][k] != b[2][k]]
        if bad:
            k = bad[0]
            out.append(f'{path}: {len(bad)} of {len(a[2])} elements differ, first [{k}] {a[2][k]} vs {b[2][k]}')
    elif a != b:
        out.append(f'{path}: {short(a)} vs {short(b)}')


def short(v):
    s = repr(v)
    return s if len(s) < 160 else s[:160] + '...'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('a')
    p.add_argument('b')
    p.add_argument('--limit', type=int, default=40)
    a = p.parse_args()
    x = decode(open(a.a, 'rb').read())
    y = decode(open(a.b, 'rb').read())
    out = []
    walk(x, y, '$', out, a.limit)
    print('\n'.join(out) if out else 'same')


if __name__ == '__main__':
    sys.exit(main())
