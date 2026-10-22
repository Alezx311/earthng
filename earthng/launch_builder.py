"""Open Map Builder so that a failed start is seen and logged instead of a closing console.

    MapBuilder.bat
    python earthng/launch_builder.py           checks Python, Tk, packages; opens the window, waits for it
    python earthng/launch_builder.py --check   checks only (Setup.bat)
    pythonw earthng/launch_builder.py --gui    the window itself; failures go to the log and a message box

Exit codes: 0 window shown, 2 failure explained in the console, 3 packages missing (run Setup.bat).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Import name -> requirements-fast.txt name.
PACKAGES = {'numpy': 'numpy', 'shapely': 'shapely', 'pyproj': 'pyproj', 'osmium': 'osmium', 'PIL': 'Pillow'}
TCL_VARS = ('TCL_LIBRARY', 'TK_LIBRARY', 'TIX_LIBRARY')
TK_PROBE = ('import tkinter; root = tkinter.Tk(); root.withdraw()\n'
            'from PIL import Image, ImageTk; ImageTk.PhotoImage(Image.new("RGB", (1, 1)))\n'
            'root.destroy()')
FAILED, MISSING = 2, 3
WAIT = 120


class StartupError(Exception):
    """A failure the user can act on; the message says what to do."""


def log_dir(root=ROOT):
    """out/mapbuilder in this folder, or %TEMP% when the folder is read-only."""
    for folder in (Path(root) / 'out' / 'mapbuilder', Path(tempfile.gettempdir()) / 'EarthNG-MapBuilder'):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / '.write-test'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink()
            return folder
        except OSError:
            continue
    raise StartupError('No writable folder for the Map Builder log. Extract the archive to a folder you own, '
                       'for example Documents\\EarthNG-MapBuilder.')


def required_names(root=ROOT):
    names = []
    for line in (Path(root) / 'requirements-fast.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#')[0].strip()
        if line:
            names.append(line.split('==')[0].split('>=')[0].strip())
    return names


def check_files(root=ROOT):
    needed = ['earthng/country_ui.py', 'earthng/builder_map.py', 'earthng/country_fetch.py', 'requirements-fast.txt']
    missing = [name for name in needed if not (Path(root) / name).is_file()]
    if missing:
        raise StartupError(f'Map Builder files are missing: {", ".join(missing)}.\n'
                           'Extract the ENTIRE EarthNG-MapBuilder.zip to a writable folder and run MapBuilder.bat '
                           'from there (not from inside the ZIP window).')
    if not os.access(root, os.W_OK):
        raise StartupError(f'{root} is not writable. Move the extracted folder somewhere you own, '
                           'for example Documents, and run MapBuilder.bat again.')


def check_python():
    notes = []
    if sys.version_info[:2] < (3, 13):
        raise StartupError(f'Python {sys.version.split()[0]} at {sys.executable} is too old; Map Builder needs 3.13.\n'
                           'Install Python 3.13 from python.org (tick "tcl/tk and IDLE" and "py launcher"), '
                           'delete the .venv folder here and run MapBuilder.bat again.')
    if sys.version_info[:2] != (3, 13):
        notes.append(f'Python {sys.version.split()[0]} is untested; packages are pinned for 3.13.')
    return notes


def missing_packages():
    missing = []
    for module, name in PACKAGES.items():
        try:
            importlib.import_module(module)
        except Exception as exc:  # broken wheels raise more than ImportError
            missing.append(f'{name} ({type(exc).__name__}: {exc})')
    return missing


def probe_tk(python, env):
    """Create a hidden Tk window in a fresh interpreter: returns (ok, error text)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        result = subprocess.run([str(python), '-c', TK_PROBE], env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=60, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f'{type(exc).__name__}: {exc}'
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def tk_environment(python=sys.executable, env=None, probe=probe_tk):
    """Environment in which Tk opens; drops foreign TCL_LIBRARY/TK_LIBRARY when those break it."""
    env = dict(os.environ if env is None else env)
    ok, error = probe(python, env)
    if ok:
        return env, []
    foreign = {name: env[name] for name in TCL_VARS if name in env}
    if foreign:
        clean = {k: v for k, v in env.items() if k not in TCL_VARS}
        if probe(python, clean)[0]:
            listed = ', '.join(f'{k}={v}' for k, v in foreign.items())
            return clean, [f'Ignored {listed}: another program set it and it breaks Python Tk.']
    last = error.splitlines()[-1] if error else 'no error text'
    if 'No module named' in error and 'tkinter' in error:
        advice = ('This Python has no Tcl/Tk. Run the Python 3.13 installer again, choose Modify, '
                  'tick "tcl/tk and IDLE", finish, then run MapBuilder.bat again.')
    elif foreign:
        advice = (f'Tk fails even without {", ".join(foreign)}. Repair Python 3.13 with its installer '
                  '(Modify > tcl/tk and IDLE).')
    else:
        advice = ('Repair Python 3.13 with its installer (Modify > tick "tcl/tk and IDLE"). '
                  'If Python is installed in a folder with non-English letters, reinstall it to a plain path.')
    raise StartupError(f'Python cannot open a window (Tk): {last}\n{advice}\n\nFull error:\n{error}')


def gui_python(python=sys.executable):
    python = Path(python)
    windowed = python.with_name('pythonw.exe')
    return windowed if os.name == 'nt' and windowed.is_file() else python


def preflight(after_setup=False, python=sys.executable, probe=probe_tk, root=ROOT):
    """Returns (environment for the window, notes). Raises StartupError or SystemExit(MISSING)."""
    check_files(root)
    notes = check_python()
    missing = missing_packages()
    if missing:
        if not after_setup:
            print('Python packages are missing or broken: ' + ', '.join(missing))
            raise SystemExit(MISSING)
        raise StartupError('Packages still fail after Setup.bat: ' + '; '.join(missing) + '\n'
                           'Check the Setup.bat messages above (internet, antivirus, disk space). '
                           'Deleting the .venv folder and running MapBuilder.bat again reinstalls them.')
    env, tk_notes = tk_environment(python, probe=probe)
    return env, notes + tk_notes


def tail(path, lines=30):
    try:
        return '\n'.join(Path(path).read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    except OSError:
        return ''


def read_status(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_status(path, state, **extra):
    Path(path).write_text(json.dumps({'state': state, 'time': time.time(), **extra}), encoding='utf-8')


def start_window(env, folder, wait=WAIT, python=sys.executable, command=None):
    """Start the window detached, then wait until it reports itself shown or exits."""
    log = folder / 'startup.log'
    status = folder / 'startup.json'
    status.unlink(missing_ok=True)
    command = command or [str(gui_python(python)), str(Path(__file__).resolve()), '--gui', '--status']
    env = {**env, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONFAULTHANDLER': '1'}
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
    with log.open('a', encoding='utf-8') as stream:
        process = subprocess.Popen([*command, str(status)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                   creationflags=flags, close_fds=True)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        state = read_status(status).get('state')
        if state == 'shown':
            return True
        code = process.poll()
        if code is not None or state == 'failed':
            # On 'failed' the window process may still show its error box; do not wait for it.
            ended = f'exit code {code}' if code is not None else 'error box shown'
            raise StartupError(f'The Map Builder window failed during start ({ended}).\n'
                               f'Last lines of {log}:\n{tail(log)}')
        time.sleep(0.2)
    print(f'The window is still starting after {wait} s; it may appear shortly. Log: {log}')
    return False


def open_log(folder):
    log = folder / 'startup.log'
    if log.exists():
        log.replace(folder / 'startup.prev.log')
    stream = log.open('w', encoding='utf-8')
    stream.write(f'EarthNG Map Builder start {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
                 f'python {sys.executable} {sys.version}\nfolder {ROOT}\n')
    for name in TCL_VARS:
        if name in os.environ:
            stream.write(f'{name}={os.environ[name]}\n')
    return stream


def launch(argv):
    folder = log_dir()
    stream = open_log(folder)
    try:
        env, notes = preflight(after_setup='--after-setup' in argv)
        for note in notes:
            print(note)
            stream.write(note + '\n')
        if '--check' in argv:
            print('Python, Tk and packages are ready.')
            return 0
        stream.write('checks passed; starting the window\n')
        stream.close()
        print('Opening EarthNG Map Builder...')
        start_window(env, folder)
        return 0
    except SystemExit:
        stream.write('packages missing; MapBuilder.bat runs Setup.bat\n')
        raise
    except StartupError as exc:
        message = str(exc)
        if not stream.closed:
            stream.write('FAILED\n' + message + '\n')
        else:
            with (folder / 'startup.log').open('a', encoding='utf-8') as again:
                again.write('FAILED\n' + message + '\n')
        print('\nEarthNG Map Builder could not start.\n\n' + message)
        print(f'\nThis message is saved in {folder / "startup.log"} - attach it to a GitHub issue if it does not help.')
        return FAILED
    finally:
        if not stream.closed:
            stream.close()


def show_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        box = tk.Tk()
        box.withdraw()
        messagebox.showerror('EarthNG Map Builder', message, parent=box)
        box.destroy()
    except Exception:
        pass


def run_gui(status):
    """The window, as country_ui.main, plus a shown/failed status and logged callback errors."""
    import threading
    root = None
    try:
        sys.path.insert(0, str(HERE))
        import tkinter as tk
        import country_ui

        def report(kind, value, tb):
            traceback.print_exception(kind, value, tb)
            sys.stderr.flush()
        tk.Tk.report_callback_exception = lambda _self, *info: report(*info)
        threading.excepthook = lambda info: report(info.exc_type, info.exc_value, info.exc_traceback)
        root = tk.Tk()
        country_ui.Setup(root)
        root.after_idle(lambda: status and write_status(status, 'shown'))
        root.mainloop()
        return 0
    except Exception as exc:
        details = traceback.format_exc()
        print(details, file=sys.stderr, flush=True)
        if status:
            write_status(status, 'failed', error=details)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        log = Path(status).with_name('startup.log') if status else 'out/mapbuilder/startup.log'
        show_error(f'Map Builder could not start:\n{type(exc).__name__}: {exc}\n\nDetails: {log}')
        return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--status')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--after-setup', action='store_true')
    args = parser.parse_args(argv)
    if args.gui:
        return run_gui(args.status)
    return launch(argv)


if __name__ == '__main__':
    raise SystemExit(main())
