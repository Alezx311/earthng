"""Small, checkout-local helpers for the Windows BeamNG integration test."""
import os
from pathlib import Path
import re

import psutil


def game_exe():
    from fast_art import game_dir
    override = os.environ.get('BEAMNG_EXE')
    install = game_dir()
    path = Path(override) if override else (install / 'Bin64/BeamNG.drive.x64.exe' if install else None)
    if path is None or not path.is_file():
        raise FileNotFoundError('BeamNG executable not found. Set BEAMNG_EXE to its full path.')
    return path


def memory(pid):
    try:
        info = psutil.Process(pid).memory_info()
        return getattr(info, 'private', info.rss), info.rss
    except psutil.Error:
        return None


def log_metrics(path):
    text = Path(path).read_text(encoding='utf8', errors='replace') if Path(path).exists() else ''
    result = {'collada_imports': text.count('Importing COLLADA')}
    result['render_sizes'] = list(dict.fromkeys(re.findall(r'init begin: size=(\d+x\d+)', text)))
    loaded = re.search(r'Level loaded in ([\d.]+)s: (.*)', text)
    if loaded:
        result['level_load_s'] = float(loaded[1])
        result['load_parts_s'] = {k: float(v) for k, v in re.findall(r'([\w.]+) ([\d.]+)s', loaded[2])}
    collision = re.search(r'Physics collision reloaded in [\d.]+s \((\d+) instances generated in [\d.]+s, using ([\d.]+)mb\)', text)
    if collision:
        result.update(collision_instances=int(collision[1]), collision_mb=float(collision[2]))
    return result
