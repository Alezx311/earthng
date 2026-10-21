"""Native in-game smoke/benchmark in a disposable BeamNG profile.

python earthng/test_world.py --out out/nyc --lat 40.758 --lon -73.9855 --mod out/native-packs/earthng_new-york.zip
The user's normal profile is never changed. Requires requirements-dev.txt and BeamNG.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from game_bench import game_exe, log_metrics, memory
import build_mod  # noqa: E402


def geo_point(point):
    """'lat,lon,agl' or [lat, lon, agl] -> [lat, lon, z]: z in the game's frame (DEM height + the world's lift).
    A height ending in 'a' is metres above sea level instead (a photo's camera altitude)."""
    import fast_dem
    from fast_sources import LIFT
    lat, lon, h = (point.split(',') if isinstance(point, str) else point)
    lat, lon = float(lat), float(lon)
    if isinstance(h, str) and h.endswith('a'):
        return [lat, lon, round(float(h[:-1]) + LIFT, 2)]
    ground = fast_dem.height(lat, lon, HERE.parent / 'out' / 'world' / 'cache')
    return [lat, lon, round(ground + float(h) + LIFT, 2)]


def above_ground(point):
    """The height over the game's surface a view corrects to, or None for a sea-level altitude."""
    h = point.split(',')[2]
    return None if h.endswith('a') else float(h)


class Recorder:
    """The game's own window to an H.264 file while its e2r-rec.json says 'start' (Windows
    Graphics Capture + NVENC, so the game keeps the CPU). The window, not the monitor: a desktop
    capture recorded whatever was on top of a game the player had covered."""

    def __init__(self, out, fps):
        self.out, self.fps, self.state, self.proc, self.clips = out, fps, None, None, []

    def poll(self, marker):
        try:
            rec = json.loads(marker.read_text(encoding='utf8')) if marker.exists() else {}
        except (OSError, ValueError):
            return
        state = rec.get('rec')
        if state == self.state:
            return
        self.state = state
        if state == 'start' and self.proc is None:
            clip = self.out / f"{rec.get('clip') or 'clip'}-{len(self.clips) + 1:02d}.mp4"
            self.clips.append(clip.name)
            self.proc = subprocess.Popen(
                [shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                 '-i', f'gfxcapture=window_exe=BeamNG.drive.x64.exe:max_framerate={self.fps}:capture_cursor=0',
                 '-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '18', '-b:v', '0', str(clip)],
                stdin=subprocess.PIPE)
        elif state == 'stop':
            self.stop()

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.communicate(b'q', timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                self.proc.kill()
            self.proc = None


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--lat', type=float, help='landing point; with --replay the route start by default')
    p.add_argument('--lon', type=float)
    p.add_argument('--timeout', type=int, default=420)
    p.add_argument('--route', type=Path, help='route.json (earthng/route.py) for the autopilot')
    p.add_argument('--speed', type=float, default=13.0, help='autopilot cruise speed, m/s')
    p.add_argument('--drive-seconds', type=float, default=8)
    p.add_argument('--packs', action='store_true', help='after the drive: an overview shot in every texture pack')
    p.add_argument('--gallery', action='store_true', help='after the drive: fixed views round the car (e2r-g*.png)')
    p.add_argument('--pack', help='texture pack to land and drive in (default real)')
    p.add_argument('--pack-gallery', help='comma list of packs: the gallery once in each (implies --gallery)')
    p.add_argument('--gallery-wait', type=float, default=1, help='seconds before the gallery (far tiles keep loading)')
    p.add_argument('--view', action='append', default=[], help='extra gallery view name:x,y,z:tx,ty,tz (world metres)')
    p.add_argument('--geo-view', action='append', default=[], metavar='NAME:LAT,LON,AGL:LAT,LON,AGL[:FOV]',
                   help='extra gallery view by coordinates, heights in metres above the ground (or 123a: above sea level), optional FOV')
    p.add_argument('--only-views', action='store_true', help='the gallery is only --view/--geo-view, not the views round the car')
    p.add_argument('--view-settle', type=float, help='each view waits until loading stops, at most this many seconds')
    p.add_argument('--tod', type=float, help="time of day after landing (the game's 0..1, 0 noon, 0.25 dusk)")
    p.add_argument('--clean', action='store_true', help='no EarthNG window on screen (recorded video)')
    p.add_argument('--fog', type=float, help='fog density after landing (the level: 0.00015)')
    p.add_argument('--gen-budget', type=float, help='ms a frame for generation and spawning (stills; the game uses 4)')
    p.add_argument('--lights', type=int, help='street lights of night packs (stills; the game uses 24 within 400 m)')
    p.add_argument('--flight', type=Path, help='camera flight after the drive: {"speed", "keys": [{"cam": [lat, lon, agl], "at": [...]}]}')
    p.add_argument('--record', action='store_true', help='record the flight (and the drive with --record-drive) to MP4 in --out')
    p.add_argument('--record-drive', action='store_true', help='with --record: the drive is a clip too')
    p.add_argument('--record-fps', type=int, default=60)
    p.add_argument('--resolution', default='1280x720', help='game window, WxH')
    p.add_argument('--graphics', default='Normal', help="the game's preset: Lowest, Low, Normal, High, Ultra")
    p.add_argument('--display', default='Window', choices=('Window', 'Borderless', 'Fullscreen'))
    p.add_argument('--manual', action='store_true', help='land, then hand the car to the player; runs until the game is closed')
    p.add_argument('--probe', action='store_true', help='add the e2rprobe mod (earthng/probe.py runs Lua in the game)')
    p.add_argument('--min-distance', type=float, default=20, help='physics test fails below this, m')
    p.add_argument('--native', action='store_true', default=True, help='native mode (default; retained for existing commands)')
    p.add_argument('--planet', type=Path, help='test an existing planet ZIP (for repeatable before/after runs)')
    p.add_argument('--quality', type=int, choices=range(101), metavar='0..100', help='native world quality preset')
    p.add_argument('--quality-cycle', action='store_true', help='after driving, verify Potato/OASIS changes keep the road')
    p.add_argument('--picker-only', action='store_true', help='verify native picker without landing')
    p.add_argument('--expected-countries', type=int, default=0, help='country count for --picker-only')
    p.add_argument('--picker-zoom', type=int, help='--picker-only: centre the map on --lat/--lon at this zoom')
    p.add_argument('--picker-hold', type=float, default=4, help='--picker-only: seconds the picker stays open')
    p.add_argument('--replay', action='store_true', help='camera/pose replay at constant speed; not a physics test')
    p.add_argument('--traffic', type=int, help="after landing: the game's AI traffic, this many cars")
    p.add_argument('--rain', type=int, help="after landing: the game's own rain (core_environment numOfDrops)")
    p.add_argument('--mod', action='append', default=[], type=Path, help='another mod ZIP for the test profile (e.g. Agent Traffic)')
    p.add_argument('--stream-cache', type=Path, help='copy an earlier e2r_stream folder in (warm tiles)')
    p.add_argument('--hop', action='append', default=[], metavar='LAT,LON[,STAGE]',
                   help='after landing, teleport here (from driving, or STAGE spawning/warmup mid-descent); repeatable')
    a = p.parse_args()
    native_route = a.route and 'geo' in json.loads(a.route.read_text(encoding='utf8'))
    if a.route and not native_route:
        p.error('--route requires a native route with geo coordinates')
    if native_route and a.lat is None:
        a.lat, a.lon = json.loads(a.route.read_text(encoding='utf8'))['geo'][0]
    if a.picker_only:
        a.lat, a.lon = a.lat or 0, a.lon or 0
    if a.lat is None or a.lon is None:
        p.error('--lat and --lon are required')
    out = a.out.resolve()
    if out.exists():
        raise SystemExit(f'{out} exists')
    user = out / 'user'
    profile = user / 'current'
    (profile / 'mods').mkdir(parents=True)
    shutil.copy2(a.planet or build_mod.build(out / 'mod'), profile / 'mods' / build_mod.ZIP)
    if a.probe:
        # the development probe (earthng/probe.py): Lua commands into the running game
        shutil.copytree(HERE / 'probe', profile / 'mods' / 'unpacked' / 'e2rprobe')
    for extra in a.mod:
        try:
            # big country packs: a hard link on the same drive, not gigabytes of copies
            os.link(extra, profile / 'mods' / extra.name)
        except OSError:
            shutil.copy2(extra, profile / 'mods' / extra.name)
    (profile / 'settings').mkdir()
    width, height = (int(v) for v in a.resolution.lower().split('x'))
    (profile / 'settings/settings.json').write_text(json.dumps({
        'GraphicDisplayResolutions': f'{width} {height}', 'GraphicDisplayModes': a.display,
        'GraphicFullscreen': a.display == 'Fullscreen', 'GraphicOverallQuality': a.graphics,
        'AudioMasterVol': 0, 'fpsLimitBackgroundEnabled': False, 'onlineFeatures': 'disable', 'telemetry': 'disable', 'PostFXMotionBlurEnabled': False,
        # the first-run "Input Changes" page pauses the simulation (fast-game-02 never moved under it)
        'showedInputLayoutPopupV37': True}), encoding='utf8')
    test = {'lat': a.lat, 'lon': a.lon, 'driveSeconds': a.drive_seconds, 'skipMap': True, 'minDistance': a.min_distance}
    if a.quality is not None:
        test['quality'] = a.quality
    if a.quality_cycle:
        test['qualityCycle'] = [0, 100]
    if a.picker_only:
        test.update(pickerOnly=True, expectedCountries=a.expected_countries, pickerHold=a.picker_hold)
        if a.picker_zoom:
            test['pickerZoom'] = a.picker_zoom
    if a.hop:
        hops = []
        for h in a.hop:
            parts = h.split(',')
            hops.append([float(parts[0]), float(parts[1])] + ([parts[2]] if len(parts) > 2 else []))
        test['hops'] = hops
    if a.route:
        shutil.copy2(a.route, profile / 'e2r-route.json')
        test.update(route='/e2r-route.json', speed=a.speed)
    if a.replay:
        if not native_route:
            p.error('--replay requires a native geo route')
        test['replay'] = True
    if a.packs:
        test['packs'] = True
    if a.pack:
        test['pack'] = a.pack
    if a.pack_gallery or a.geo_view:
        a.gallery = True
    if a.pack_gallery:
        test['packGallery'] = [s for s in a.pack_gallery.split(',') if s]
    if a.gallery:
        test['gallery'] = True
        test['galleryWait'] = a.gallery_wait
        test['views'] = [{'name': v.split(':')[0], 'cam': [float(c) for c in v.split(':')[1].split(',')],
                          'at': [float(c) for c in v.split(':')[2].split(',')]} for v in a.view]
        for v in a.geo_view:
            # the DEM height places the camera while the place loads; the game corrects it to
            # its own surface (camAgl/atAgl) before the shot
            # name:cam:target[:fov] - fov in degrees (the game's camera), to match a photo's lens
            name, cam, look, *fov = v.split(':')
            view = {'name': name, 'camGeo': geo_point(cam), 'atGeo': geo_point(look),
                    'camAgl': above_ground(cam), 'atAgl': above_ground(look)}
            if fov:
                view['fov'] = float(fov[0])
            test['views'].append(view)
        if a.only_views:
            test['onlyViews'] = True
        if a.view_settle:
            test['viewSettle'] = a.view_settle
    if a.tod is not None:
        test['tod'] = a.tod
    if a.clean:
        test['clean'] = True
    if a.fog is not None:
        test['fog'] = a.fog
    if a.gen_budget:
        test['genBudget'] = a.gen_budget
    if a.lights:
        test['lights'] = a.lights
    if a.flight:
        plan = json.loads(a.flight.read_text(encoding='utf8'))
        test['flight'] = {'keys': [{'cam': geo_point(k['cam']), 'at': geo_point(k['at'])} for k in plan['keys']],
                          'speed': plan.get('speed', 30), 'settle': plan.get('settle', 90),
                          'warmup': plan.get('warmup', True),
                          'clip': plan.get('clip', a.flight.stem)}
    if a.record_drive:
        test['recordDrive'] = True
    if a.traffic:
        test['traffic'] = a.traffic
    if a.rain:
        test['rain'] = a.rain
    if a.manual:
        test['manual'] = True
        a.timeout = 10**9
    if a.stream_cache:
        shutil.copytree(a.stream_cache, profile / 'e2r_stream')
    (profile / 'e2r-world-test.json').write_text(json.dumps(test), encoding='utf8')
    if a.native:
        test['skipMap'] = True  # native picker has an offline vector map instead of downloaded textures
        test_file = profile / 'e2r-world-test.json'
        test_file.write_text(json.dumps(test), encoding='utf8')
    EXE = game_exe()
    started = time.perf_counter()
    game = subprocess.Popen([str(EXE), '-userpath', str(user), '-level', build_mod.LEVEL, '-nosteam'], cwd=str(EXE.parent))
    peak = 0
    recorder = Recorder(out, a.record_fps) if a.record else None
    try:
        test_file = profile / 'e2r-world-test.json'
        res_path = profile / 'e2r-world-result.json'
        finished = None
        while game.poll() is None and time.perf_counter() - started < a.timeout:
            # the test ends with the game's shutdown(), which sometimes leaves the game open
            # (native-final-kyiv, native-hops-03): a final status 15 s old ends it from here
            try:
                status = json.loads(res_path.read_text(encoding='utf8')).get('status') if res_path.exists() else None
            except (OSError, ValueError):
                status = None
            if status in ('passed', 'failed'):
                finished = finished or time.perf_counter()
                if time.perf_counter() - finished > 15:
                    break
            else:
                finished = None
            # the game's first start in a new profile removes unknown files; keep putting it back
            if not test_file.exists() and not res_path.exists():
                test_file.write_text(json.dumps(test), encoding='utf8')
                if a.route and not (profile / 'e2r-route.json').exists():
                    shutil.copy2(a.route, profile / 'e2r-route.json')
            m = memory(game.pid)
            if m:
                peak = max(peak, m[0])
            if recorder:
                recorder.poll(profile / 'e2r-rec.json')
            time.sleep(0.2 if recorder else 0.5)
        if game.poll() is None:
            game.kill()
    finally:
        if recorder:
            recorder.stop()
        if game.poll() is None:
            game.kill()
        game.wait(timeout=30)
    res_path = profile / 'e2r-world-result.json'
    result = json.loads(res_path.read_text(encoding='utf8')) if res_path.exists() else {'status': 'no_result'}
    for png in sorted((profile / 'screenshots').rglob('e2r-*.png')):
        shutil.copy2(png, out / png.name)
    if (profile / 'beamng.log').exists():
        shutil.copy2(profile / 'beamng.log', out / 'beamng.log')
    report = {'status': result.get('status'), 'exit_code': game.returncode,
              'native': a.native, 'physics_test': not a.replay and not a.picker_only,
              'clips': recorder.clips if recorder else [],
              'total_s': round(time.perf_counter() - started, 1), 'peak_private_mb': round(peak / 2**20),
              'game': result, 'log': log_metrics(out / 'beamng.log')}
    if 'failures' in result:
        functional = [f for f in result['failures'] if f != 'frame_over_100ms']
        report['functional_status'] = 'failed' if functional else 'passed'
        report['performance_status'] = 'failed' if 'frame_over_100ms' in result['failures'] else 'passed'
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k != 'game'}, indent=2))
    print('status', report['status'], 'failures', result.get('failures'), 'travelled_m', result.get('travelledM'),
          'drive_frames', result.get('driveFrames'))
    sys.exit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
