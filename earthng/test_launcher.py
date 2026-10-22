"""MapBuilder start: checks, visible failures, window handshake and the release bundle (issue #4)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import launch_builder as launcher
import prepare_release

ROOT = Path(__file__).resolve().parents[1]


def probe_from(results):
    calls = []

    def probe(_python, env):
        calls.append(dict(env))
        return results[len(calls) - 1]
    return probe, calls


class CheckTests(unittest.TestCase):
    def test_package_table_matches_requirements(self):
        self.assertEqual(sorted(launcher.PACKAGES.values()), sorted(launcher.required_names(ROOT)))

    def test_missing_files_explain_extracting_the_whole_zip(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(launcher.StartupError, 'ENTIRE'):
            launcher.check_files(tmp)

    def test_tk_ok_keeps_environment(self):
        probe, calls = probe_from([(True, '')])
        env, notes = launcher.tk_environment(env={'TCL_LIBRARY': 'x'}, probe=probe)
        self.assertEqual(env, {'TCL_LIBRARY': 'x'})
        self.assertEqual((notes, len(calls)), ([], 1))

    def test_foreign_tcl_variables_are_dropped_when_they_break_tk(self):
        probe, calls = probe_from([(False, "Can't find a usable init.tcl"), (True, '')])
        env, notes = launcher.tk_environment(env={'TCL_LIBRARY': r'C:\QGIS\tcl', 'PATH': 'p'}, probe=probe)
        self.assertEqual(env, {'PATH': 'p'})
        self.assertNotIn('TCL_LIBRARY', calls[1])
        self.assertIn('TCL_LIBRARY', notes[0])

    def test_missing_tcl_tk_says_how_to_modify_the_installer(self):
        probe, _ = probe_from([(False, "ModuleNotFoundError: No module named 'tkinter'")])
        with self.assertRaisesRegex(launcher.StartupError, 'tcl/tk and IDLE'):
            launcher.tk_environment(env={}, probe=probe)

    def test_tk_still_broken_without_foreign_variables(self):
        probe, _ = probe_from([(False, 'TclError: a'), (False, 'TclError: b')])
        with self.assertRaisesRegex(launcher.StartupError, 'even without TK_LIBRARY'):
            launcher.tk_environment(env={'TK_LIBRARY': 'x'}, probe=probe)

    def test_missing_packages_ask_for_setup_once_then_fail_visibly(self):
        ok = lambda *_: (True, '')
        with patch.object(launcher, 'missing_packages', return_value=['shapely (ImportError: x)']):
            with self.assertRaises(SystemExit) as stop:
                launcher.preflight(probe=ok)
            self.assertEqual(stop.exception.code, launcher.MISSING)
            with self.assertRaisesRegex(launcher.StartupError, 'still fail after Setup'):
                launcher.preflight(after_setup=True, probe=ok)

    def test_real_interpreter_passes(self):
        env, _notes = launcher.preflight()
        self.assertIsInstance(env, dict)

    def test_log_falls_back_to_temp_when_folder_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / 'file'
            blocker.write_text('not a folder')
            folder = launcher.log_dir(blocker)
            self.assertNotIn(str(blocker), str(folder))
            self.assertTrue(folder.is_dir())


class WindowTests(unittest.TestCase):
    def window(self, code, wait=30):
        # A still-starting child keeps the log open; it exits by itself.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp)
            command = [sys.executable, '-c', code]
            try:
                return launcher.start_window(dict(os.environ), folder, wait=wait, command=command), None
            except launcher.StartupError as exc:
                return None, str(exc)

    def test_shown_window_returns(self):
        code = ('import json, sys, time; open(sys.argv[1], "w").write(json.dumps({"state": "shown"}))')
        self.assertEqual(self.window(code), (True, None))

    def test_early_exit_reports_its_log(self):
        code = 'import sys; print("Traceback: boom", file=sys.stderr); sys.exit(1)'
        shown, error = self.window(code)
        self.assertIsNone(shown)
        self.assertIn('exit code 1', error)
        self.assertIn('Traceback: boom', error)

    def test_slow_start_is_not_an_error(self):
        self.assertEqual(self.window('import time; time.sleep(3)', wait=0.5), (False, None))

    def test_gui_failure_writes_status_and_shows_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'startup.json'
            fake_ui = MagicMock()
            fake_ui.Setup.side_effect = RuntimeError('broken region list')
            with patch.dict(sys.modules, {'country_ui': fake_ui}), patch('tkinter.Tk') as tk_class, \
                    patch('threading.excepthook'), patch.object(launcher, 'show_error') as shown:
                self.assertEqual(launcher.run_gui(str(status)), 1)
            data = json.loads(status.read_text())
            self.assertEqual(data['state'], 'failed')
            self.assertIn('broken region list', data['error'])
            self.assertIn('broken region list', shown.call_args[0][0])
            tk_class.return_value.destroy.assert_called_once()


class BundleTests(unittest.TestCase):
    def test_release_bundle_contains_the_launcher_and_its_scripts(self):
        names = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
        names += ['earthng/launch_builder.py']
        files = {n: (ROOT / n).read_bytes() for n in names if (ROOT / n).is_file()}
        selected = prepare_release.builder_files(files)
        for name in ('MapBuilder.bat', 'Setup.bat', 'earthng/launch_builder.py', 'earthng/country_ui.py',
                     'requirements-fast.txt'):
            self.assertIn(name, selected)
        batch = selected['MapBuilder.bat'].decode('ascii')
        self.assertIn('launch_builder.py', batch)
        self.assertNotIn('start ""', batch)  # silent pythonw start was the issue #4 failure


if __name__ == '__main__':
    unittest.main()
