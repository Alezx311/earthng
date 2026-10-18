"""Stage reviewable release files locally; never publish or modify the game profile.

python earthng/prepare_release.py --out out/release/0.4.0 --planet out/mod/earthng_planet.zip
Stage intended source files in Git first; the source ZIP uses current tracked files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def archive_files(target, files):
    temporary = target.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT).as_posix())
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--planet', type=Path, required=True)
    parser.add_argument('--country', type=Path, action='append', default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.planet) as archive:
        manifest = json.loads(archive.read('earthng/planet/manifest.json'))
        if manifest.get('runtime') != 'lua':
            raise ValueError('release requires the native planet')
        if any(name.startswith(('content/', 'python/')) for name in archive.namelist()):
            raise ValueError('unexpected game/runtime files in planet')
    for source in [args.planet, *args.country]:
        shutil.copyfile(source, args.out / source.name)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    files = [ROOT / name for name in tracked if name and (ROOT / name).is_file()]
    archive_files(args.out / 'earthng-source.zip', files)
    # Explicit allowlist: no game assets, profiles, downloaded PBFs or private settings.
    assets = []
    for folder in ('data/textures', 'data/art-distributable', 'out/basemap'):
        assets.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                      and p.suffix.lower() in ('.jpg', '.png', '.dds', '.json'))
    if not assets:
        raise FileNotFoundError('developer assets have not been built')
    archive_files(args.out / 'earthng-developer-assets.zip', assets)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT / name, args.out / name)
    hashes = []
    for path in sorted(args.out.iterdir()):
        if path.is_file() and path.name != 'SHA256SUMS.txt':
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            hashes.append(f'{digest}  {path.name}')
    (args.out / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf8')
    print(args.out.resolve())


if __name__ == '__main__':
    main()
