"""Build a map selection as independently installable, resumable country sections."""
import hashlib
import json
from pathlib import Path

import country_fetch
import places


def build(plan, by_id, mods, root, *, look=None, include=None, jobs=None, allow_pbf=False,
          emit=print, cancel=None, progress=None, on_part=None):
    root, mods = Path(root), Path(mods)
    parts = plan['parts']
    if not parts:
        raise ValueError('No regional source covers this selection.')
    # A retry after Stop (even after restarting the app) resumes already installed ZIPs.
    # Finishing a build clears the receipt so creating the same map again rebuilds it.
    sources = [(p['place'], p['section']['id']) for p in parts]
    snapshots = []
    for key in dict.fromkeys(p['place'] for p in parts):
        path = country_fetch.pbf_path(root, places.slug(key))
        stat = path.stat() if path.is_file() else None
        snapshots.append((key, (stat.st_size, stat.st_mtime_ns) if stat else None))
    code = hashlib.sha256()
    for filename in ('selection_build.py', 'build_country.py', 'fast_sources.py', 'fast_style.py', 'country_format.py'):
        code.update(Path(__file__).with_name(filename).read_bytes())
    identity = json.dumps([str(mods.resolve()), sources, look, include, code.hexdigest()], sort_keys=True)
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    work = root / 'out' / 'world'
    receipt = work / f'selection-{digest}.json'
    installed = []
    with country_fetch.build_lock(work):
        try:
            prior = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
        except (OSError, ValueError):
            prior = {}
        for key, stamp in snapshots:
            if key in prior.get('_sources', {}) and prior['_sources'][key] != (list(stamp) if stamp else None):
                prior = {}
                break
        for i, part in enumerate(parts, 1):
            country_fetch.check_stopped(cancel)
            place = by_id[part['place']]
            section = part['section']
            if on_part:
                on_part(i, len(parts), place['name'])
            slug = places.slug(place['id'])
            filename = f"earthng_{slug}_{section['id']}.zip"
            target = mods / 'mods' / filename
            if filename in prior and target.is_file():
                stat = target.stat()
                if prior[filename] == [stat.st_size, stat.st_mtime_ns]:
                    emit(f'[{i}/{len(parts)}] Reusing installed {filename}')
                    installed.append(target)
                    continue
            emit(f"[{i}/{len(parts)}] {place['name']} · {section['name']}")
            try:
                path = country_fetch._build_place(place, mods, root=root, section=section, jobs=jobs,
                                                  by_id=by_id, look=look, include=include, emit=emit,
                                                  progress=progress, cancel=cancel, allow_pbf=allow_pbf)
            except country_fetch.EmptySelection as exc:
                emit(f'Skipping section without drivable coverage: {exc}')
                continue
            except country_fetch.NeedsPbf as exc:
                exc.offer = {'place': place['id'], 'name': place['name']}
                raise
            stat = path.stat()
            prior[filename] = [stat.st_size, stat.st_mtime_ns]
            pbf = country_fetch.pbf_path(root, slug)
            if pbf.is_file():
                source_stat = pbf.stat()
                prior.setdefault('_sources', {})[part['place']] = [source_stat.st_size, source_stat.st_mtime_ns]
            tmp = receipt.with_suffix('.tmp')
            tmp.write_text(json.dumps(prior), encoding='utf-8')
            tmp.replace(receipt)
            installed.append(path)
        if not installed:
            raise ValueError('No section contains a road with enough surrounding terrain to land.')
        receipt.unlink(missing_ok=True)
    return installed
