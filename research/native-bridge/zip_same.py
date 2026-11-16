"""Compare the ZIPs of two output folders entry by entry (MapBuilder's same-bytes rule).

    python research/native-bridge/zip_same.py A_DIR B_DIR

ZIPs are matched by file name; each entry's bytes are compared (not the archive bytes:
timestamps in the ZIP headers may differ). Prints a line per ZIP and the first differing entries.
"""
import sys
import zipfile
from pathlib import Path


def main(a_dir, b_dir):
    a_dir, b_dir = Path(a_dir), Path(b_dir)
    zips = sorted(p.name for p in a_dir.rglob('*.zip'))
    if not zips:
        print('no ZIP in', a_dir)
        return 1
    bad = 0
    for name in zips:
        a, b = next(a_dir.rglob(name)), next(b_dir.rglob(name), None)
        if b is None:
            print(f'{name}: missing in {b_dir}')
            bad += 1
            continue
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            na, nb = set(za.namelist()), set(zb.namelist())
            diff = sorted(n for n in na & nb if za.read(n) != zb.read(n))
            only_a, only_b = sorted(na - nb), sorted(nb - na)
            same = len(na & nb) - len(diff)
            print(f'{name}: {same}/{len(na | nb)} entries identical, {len(diff)} differ, '
                  f'{len(only_a)} only in A, {len(only_b)} only in B')
            for n in (diff[:10] + only_a[:5] + only_b[:5]):
                print('   ', n)
            bad += bool(diff or only_a or only_b)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
