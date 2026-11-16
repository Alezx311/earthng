"""Compare two folders of canonical layer dumps (<tile>-<layer>.emc): byte-equal, or where they differ.

    .venv/Scripts/python.exe research/native-bridge/parity_dirs.py out/night-1116/parity/kyiv-rust out/night-1116/parity/kyiv-lua
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import emc_diff  # noqa: E402


def main():
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    names = sorted({p.name for p in a.glob('*.emc')} | {p.name for p in b.glob('*.emc')})
    same = diff = missing = 0
    for n in names:
        pa, pb = a / n, b / n
        if not pa.exists() or not pb.exists():
            missing += 1
            print(n, 'only in', a if pa.exists() else b)
            continue
        x, y = pa.read_bytes(), pb.read_bytes()
        if x == y:
            same += 1
            continue
        diff += 1
        out = []
        emc_diff.walk(emc_diff.decode(x), emc_diff.decode(y), '$', out, 4)
        print(n, len(x), len(y), *out, sep='\n  ')
    print(f'same {same} diff {diff} missing {missing}')
    return 1 if diff or missing else 0


if __name__ == '__main__':
    sys.exit(main())
