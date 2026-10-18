"""Window: download a ready map pack, or build one with its own layers and assets.

    MapBuilder.bat
    pythonw earthng/country_ui.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import country_fetch
import looks
import places
import builder_estimate as timing
from builder_map import MapData, RegionMap
from PIL import ImageTk

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SETTINGS = ROOT / 'country_setup.json'
HISTORY = ROOT / 'out' / 'country-setup' / 'build-times.json'


def load_settings():
    mods = str(country_fetch.default_mods())
    settings = {'mods': mods, 'query': ''}
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            saved = {}
        if isinstance(saved, dict) and isinstance(saved.get('mods'), str):
            settings['mods'] = saved['mods']
    return settings


def save_settings(mods):
    SETTINGS.write_text(json.dumps({'mods': mods}, ensure_ascii=False, indent=1), encoding='utf-8')


class Setup:
    def __init__(self, root, start_workers=True):
        self.root = root
        self.settings = load_settings()
        self.places = []
        self.by_id = {}
        self.shown = []
        self.place = None
        self.lines = queue.Queue()
        self.cancel = None
        self.worker = None
        self.running = False
        self.boundaries = {}
        self.sizes = {}
        self.size_future = None
        self.preview_future = None
        self.preview_version = 0
        self.preview_after = None
        self.map_after = None
        self.map_version = 0
        self.pool = ThreadPoolExecutor(3, thread_name_prefix='mapbuilder')
        self.history = timing.load_history(HISTORY)
        self.stage_times = {}
        self.active_stage = None
        self.started = None
        self.closing = False
        self.freeze = False
        self.start_workers = start_workers
        root.title('EarthNG — Map Builder')
        root.geometry('1220x900')
        root.minsize(1040, 860)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.mods = tk.StringVar(value=self.settings['mods'])
        self.query = tk.StringVar(value='')
        self.status = tk.StringVar(value='Loading the region list…')
        self.size = tk.StringVar(value='')
        self.ready = tk.StringVar(value='')
        self.estimate_text = tk.StringVar(value='Choose a region to estimate the build time.')
        self.progress_text = tk.StringVar(value='Ready')
        self.selection_text = tk.StringVar(value='Whole source region')
        self.preview_text = tk.StringVar(value='Material preview loading…')
        self.block = tk.StringVar()
        self.slots = {slot: tk.StringVar() for slot in looks.SLOTS}
        self.layers = {key: tk.BooleanVar(value=default) for key, _label, default in looks.LAYERS}
        self.use_box = tk.BooleanVar(value=False)
        self.box = {name: tk.StringVar() for name in ('w', 's', 'e', 'n')}
        self._build()
        self.show_look(looks.canonical({'block': 'general'}))
        for variable in [*self.slots.values(), *self.layers.values(), self.use_box, *self.box.values()]:
            variable.trace_add('write', self.options_changed)
        self.mods.trace_add('write', self.mods_changed)
        root.after(200, self.pump)
        if start_workers:
            self.reload(False)
            self.reload_map()
            self.pool.submit(self.load_boundaries)

    def _build(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer)
        top.pack(fill='x')
        ttk.Label(top, text='BeamNG user folder').pack(side='left')
        ttk.Entry(top, textvariable=self.mods).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(top, text='Browse', command=self.browse_mods).pack(side='left')
        ttk.Button(top, text='Refresh planet code', command=self.refresh_planet).pack(side='left', padx=(8, 0))

        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True, pady=8)
        left = ttk.Frame(body)
        left.pack(side='left', fill='both', expand=True)
        search = ttk.Frame(left)
        search.pack(fill='x')
        ttk.Label(search, text='Region').pack(side='left')
        entry = ttk.Entry(search, textvariable=self.query)
        entry.pack(side='left', fill='x', expand=True, padx=8)
        entry.bind('<KeyRelease>', lambda _event: self.refill())
        ttk.Button(search, text='Refresh list', command=lambda: self.reload(True)).pack(side='left')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill='x', pady=6)
        self.list = tk.Listbox(list_frame, exportselection=False, height=5)
        self.list.pack(side='left', fill='x', expand=True)
        list_scroll = ttk.Scrollbar(list_frame, command=self.list.yview)
        list_scroll.pack(side='right', fill='y')
        self.list.configure(yscrollcommand=list_scroll.set)
        self.list.bind('<<ListboxSelect>>', lambda _event: self.on_select())
        self.map = RegionMap(left, self.select_box)
        self.map.pack(fill='both', expand=True)
        ttk.Label(left, textvariable=self.selection_text, wraplength=600).pack(anchor='w', pady=4)
        selection_buttons = ttk.Frame(left)
        selection_buttons.pack(fill='x')
        ttk.Button(selection_buttons, text='Use whole region', command=self.clear_box).pack(side='left')
        ttk.Button(selection_buttons, text='Use smallest covering source', command=self.optimize_source).pack(side='left', padx=6)

        right = ttk.Frame(body, padding=(12, 0, 0, 0), width=460)
        right.pack(side='left', fill='y')
        self.controls = [top, search, selection_buttons, right]
        ttk.Label(right, textvariable=self.ready, wraplength=340).pack(anchor='w')
        ttk.Label(right, textvariable=self.size, foreground='#555').pack(anchor='w', pady=(2, 8))
        buttons = ttk.Frame(right)
        buttons.pack(fill='x', pady=(0, 8))
        self.download_btn = ttk.Button(buttons, text='Install a ready pack', command=self.download_ready)
        self.download_btn.pack(side='left')
        self.build_btn = ttk.Button(buttons, text='Build my own', command=self.build)
        self.build_btn.pack(side='left', padx=6)
        self.stop_btn = ttk.Button(buttons, text='Stop', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left')

        tabs = ttk.Notebook(right)
        tabs.pack(fill='both', expand=True)
        assets = ttk.Frame(tabs, padding=4)
        options = ttk.Frame(tabs, padding=4)
        tabs.add(assets, text='Look & preview')
        tabs.add(options, text='Layers & coordinates')
        ttk.Label(assets, text='Asset block').pack(anchor='w')
        titles = [block['title'] for block in looks.BLOCKS]
        self.block_box = ttk.Combobox(assets, textvariable=self.block, values=titles, state='readonly', width=36)
        self.block_box.pack(anchor='w', pady=(0, 6))
        self.block_box.bind('<<ComboboxSelected>>', lambda _event: self.apply_block())
        for slot, label in looks.SLOT_LABELS.items():
            row = ttk.Frame(assets)
            row.pack(fill='x', pady=1)
            ttk.Label(row, text=label, width=22).pack(side='left')
            values = list(looks.SLOTS[slot].values())
            ttk.Combobox(row, textvariable=self.slots[slot], values=values, state='readonly', width=22).pack(side='left')
        self.preview_label = ttk.Label(assets)
        self.preview_label.pack(anchor='w', pady=(8, 0))
        ttk.Label(assets, textvariable=self.preview_text, wraplength=440, foreground='#596773').pack(anchor='w')
        ttk.Label(options, text='Include layers (roads and terrain are always included)').pack(anchor='w', pady=(8, 2))
        layer_grid = ttk.Frame(options)
        layer_grid.pack(fill='x')
        for i, (key, label, _default) in enumerate(looks.LAYERS):
            ttk.Checkbutton(layer_grid, text=label, variable=self.layers[key]).grid(row=i//2, column=i%2, sticky='w', padx=(0, 10))
        box = ttk.Frame(options)
        box.pack(fill='x', pady=(8, 0))
        ttk.Checkbutton(box, text='Limit to selected area (coordinates optional)', variable=self.use_box).pack(anchor='w')
        coords = ttk.Frame(options)
        coords.pack(fill='x')
        for name, hint in (('w', 'W'), ('s', 'S'), ('e', 'E'), ('n', 'N')):
            ttk.Label(coords, text=hint).pack(side='left')
            ttk.Entry(coords, textvariable=self.box[name], width=8).pack(side='left', padx=(2, 6))

        ttk.Label(right, textvariable=self.estimate_text, wraplength=440).pack(anchor='w', pady=(10, 0))
        ttk.Label(right, text='The entire source PBF is needed on the first build.\nA smaller source can save download and scanning time.',
                  wraplength=440, foreground='#666').pack(anchor='w', pady=4)
        ttk.Label(outer, textvariable=self.progress_text).pack(anchor='w')
        self.progressbar = ttk.Progressbar(outer, mode='indeterminate')
        self.progressbar.pack(fill='x', pady=3)
        ttk.Label(outer, textvariable=self.status, foreground='#333', wraplength=1100).pack(anchor='w')
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill='x', pady=(4, 0))
        self.log = tk.Text(log_frame, height=5, wrap='word', state='disabled')
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(fill='both', expand=True)

    def say(self, text):
        self.lines.put(str(text))

    def pump(self):
        messages = []
        # Never let verbose workers monopolise Tk's event loop.
        for _ in range(150):
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            if callable(line):
                line()
                continue
            messages.append(line)
        if messages:
            self.log.configure(state='normal')
            self.log.insert('end', '\n'.join(messages) + '\n')
            count = int(self.log.index('end-1c').split('.')[0])
            if count > 2000:
                self.log.delete('1.0', f'{count-2000}.0')
            self.log.see('end')
            self.log.configure(state='disabled')
            self.status.set(messages[-1])
        if self.running and self.started is not None:
            elapsed = time.monotonic() - self.started
            label = f'Elapsed {timing.duration(elapsed)}'
            if self.active_stage:
                index = timing.STAGES.index(self.active_stage)
                label = f'{index+1}/{len(timing.STAGES)} · {self.active_stage} · {label}'
                if self.run_estimate:
                    remaining = sum(self.run_estimate[index:]) - (time.monotonic()-self.stage_started)
                    label += (f' · roughly {timing.duration(remaining*.5)}–{timing.duration(remaining*2.5)} remaining'
                              if remaining > 5 else ' · finishing this stage; estimate may be exceeded')
            self.progress_text.set(label)
        if self.closing and not self.running:
            self.pool.shutdown(wait=False, cancel_futures=True)
            if self.map.data:
                self.map.data.close()
            self.root.destroy()
            return
        self.root.after(200, self.pump)

    def close(self):
        self.closing = True
        self.stop()
        if self.running:
            self.status.set('Stopping safely before closing…')

    def reload_map(self):
        self.map_after = None
        if self.closing:
            return
        self.map_version += 1
        version, mods = self.map_version, self.mods.get()
        self.pool.submit(self.load_map, version, mods)

    def load_map(self, version, mods):
        try:
            data = MapData(ROOT, mods)
            self.lines.put(lambda: self.set_map_data(data, version))
        except Exception as exc:
            self.say(f'Offline map unavailable: {exc}')

    def load_boundaries(self):
        try:
            boundaries = places.load_boundaries(ROOT)
            self.lines.put(lambda: self.set_boundaries(boundaries))
        except Exception as exc:
            self.say(f'Region boundaries unavailable: {exc}. You can still choose a source from the list.')

    def set_map_data(self, data, version):
        if version != self.map_version or self.closing:
            data.close()
            return
        if self.map.data:
            self.map.data.close()
        self.map.data = data
        self.map.schedule()

    def set_boundaries(self, boundaries):
        self.boundaries = boundaries
        if self.place:
            self.map.boundary = boundaries.get(self.place['id'])
            self.map.fit_source()
        self.map.schedule()
        self.update_estimate()

    def select_box(self, box):
        if self.running:
            return
        try:
            box = timing.validate_box(box)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.freeze = True
        for name, value in zip(('w', 's', 'e', 'n'), box):
            self.box[name].set(f'{value:.6f}')
        self.use_box.set(True)
        self.freeze = False
        self.optimize_source()
        self.options_changed()

    def clear_box(self):
        if not self.running:
            self.use_box.set(False)

    def optimize_source(self):
        if self.running:
            return
        try:
            box = self.chosen_box()
        except ValueError:
            return
        if box is None:
            return
        key = places.smallest_covering(self.boundaries, box, self.by_id)
        if key:
            self.select_place(self.by_id[key], fit=False, preserve_look=self.place is not None)
            self.status.set(f'Smallest covering source: {self.place["name"]}')
        elif self.boundaries:
            self.status.set('No single extract fully covers this rectangle. Choose a smaller area.')
        else:
            self.status.set('Boundaries are not loaded yet. Choose a source region from the list.')

    def options_changed(self, *_args):
        if self.freeze:
            return
        try:
            box = self.chosen_box()
            self.map.selection = box
            self.selection_text.set(f'Selected area: {timing.area_km2(box):,.1f} km²' if box else 'Whole source region')
        except ValueError as exc:
            self.map.selection = None
            self.selection_text.set(str(exc))
        self.map.schedule()
        self.update_estimate()
        if self.start_workers:
            if self.preview_after:
                self.root.after_cancel(self.preview_after)
            self.preview_after = self.root.after(160, self.update_preview)

    def mods_changed(self, *_args):
        self.refresh_ready()
        self.options_changed()
        if self.start_workers:
            if self.map_after:
                self.root.after_cancel(self.map_after)
            self.map_after = self.root.after(600, self.reload_map)

    def update_preview(self):
        self.preview_after = None
        if self.closing:
            return
        self.preview_version += 1
        version = self.preview_version
        look, include, mods = self.chosen_look(), self.chosen_include(), self.mods.get()
        box = self.map.selection
        latitude = (box[1]+box[3])/2 if box else 50
        if self.preview_future:
            self.preview_future.cancel()

        def work():
            try:
                import builder_preview
                image, sources = builder_preview.render(look, include, mods, latitude)
                self.lines.put(lambda: self.show_preview(version, image, sources))
            except Exception as exc:
                self.say(f'Preview unavailable: {exc}')
        self.preview_future = self.pool.submit(work)

    def show_preview(self, version, image, sources):
        if version != self.preview_version:
            return
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_photo)
        fallback = sum(v == 'colour fallback' for v in sources.values())
        self.preview_text.set('Illustrative 2D street • real material samples; trees/props are schematic. '
                              + (f'{fallback} missing textures shown as fallback colours.' if fallback else ''))

    def estimate_inputs(self):
        if self.place is None:
            return None
        box = self.chosen_box()
        boundary = self.boundaries.get(self.place['id'])
        area = box or (list(boundary.bounds) if boundary is not None else None)
        slug = places.slug(self.place['id'])
        cached_pbf = country_fetch.pbf_path(ROOT, slug).is_file()
        cached_tiles = (country_fetch.tiles_dir(ROOT, slug, box) / 'index.json').is_file()
        include = self.chosen_include()
        key = timing.signature(self.place['id'], box, include, cached_pbf, cached_tiles)
        estimate, reason = timing.estimate(self.sizes.get(self.place['id']), area, include,
                                           cached_pbf, cached_tiles, self.history.get(key))
        return key, estimate, reason, cached_tiles

    def update_estimate(self):
        try:
            inputs = self.estimate_inputs()
        except ValueError:
            self.estimate_text.set('Finish selecting a valid area to estimate time.')
            return
        if not inputs:
            return
        _key, estimate, reason, cached = inputs
        if estimate:
            total = sum(estimate)
            self.estimate_text.set(f'Estimated build: {timing.duration(total*.5)}–{timing.duration(total*2.5)}\n'
                                   f'{reason}' + ('\nCompleted source tiles will be reused.' if cached else ''))
        else:
            self.estimate_text.set('Build time unknown: source size is unavailable. You can still build.')

    def browse_mods(self):
        chosen = filedialog.askdirectory(initialdir=self.mods.get() or os.getcwd())
        if chosen:
            self.mods.set(chosen)

    def load_places(self, refresh=False):
        try:
            loaded = places.load_index(ROOT, refresh, self.say)
            self.lines.put(lambda: self.set_places(loaded))
            self.say(f'{len(loaded)} regions. Pick a country or a smaller region inside it.')
        except Exception as exc:
            self.say(f'could not read the region list: {exc}')

    def reload(self, refresh):
        if getattr(self, 'list_future', None) and not self.list_future.done():
            return
        self.list_future = self.pool.submit(self.load_places, refresh)

    def set_places(self, loaded):
        self.places = sorted(loaded, key=lambda p: (p['name'].casefold(), p['id']))
        self.by_id = places.by_id(self.places)
        self.refill()

    def refill(self):
        needle = self.query.get().strip().casefold()
        self.shown = [place for place in self.places if not needle or needle in place['name'].casefold() or needle in place['id'].casefold()]
        self.list.delete(0, 'end')
        for place in self.shown:
            parent = places.parent_name(place, self.by_id)
            suffix = f'  —  {parent}' if parent else ''
            self.list.insert('end', f"{place['name']}{suffix}")
            if self.place and place['id'] == self.place['id']:
                self.list.selection_set('end')

    def on_select(self):
        if self.running:
            return
        selection = self.list.curselection()
        if not selection:
            return
        self.freeze = True
        self.use_box.set(False)
        self.freeze = False
        self.select_place(self.shown[selection[0]])

    def select_place(self, place, fit=True, preserve_look=False):
        self.place = place
        if not preserve_look:
            self.show_look(looks.recommended(place['id'], self.by_id))
        self.map.boundary = self.boundaries.get(place['id'])
        if fit:
            self.map.fit_source()
        self.map.schedule()
        self.refresh_ready()
        self.refill()
        if place in self.shown:
            self.list.see(self.shown.index(place))
        self.size.set(f'Source: {place["name"]} · reading PBF size…')
        if place['id'] in self.sizes:
            self.show_size(self.sizes[place['id']], place['id'])
        elif self.start_workers:
            if self.size_future:
                self.size_future.cancel()
            self.size_future = self.pool.submit(self.fetch_size, place['pbf'], place['id'])
        self.options_changed()

    def show_look(self, look):
        self.freeze = True
        block = looks.BLOCK_BY_ID[look['block']]
        self.block.set(block['title'])
        for slot, choices in looks.SLOTS.items():
            self.slots[slot].set(choices[look[slot]])
        self.freeze = False
        if hasattr(self, 'map'):
            self.options_changed()

    def apply_block(self):
        title = self.block.get()
        block = next((item for item in looks.BLOCKS if item['title'] == title), None)
        if block is None:
            return
        self.show_look({'block': block['id'], **block['look']})

    def chosen_look(self):
        title = self.block.get()
        block = next((item for item in looks.BLOCKS if item['title'] == title), looks.BLOCK_BY_ID['general'])
        look = {'block': block['id']}
        for slot, choices in looks.SLOTS.items():
            label = self.slots[slot].get()
            found = next((key for key, text in choices.items() if text == label), None)
            look[slot] = found or block['look'][slot]
        return looks.canonical(look)

    def chosen_include(self):
        return looks.canonical_include({key: bool(self.layers[key].get()) for key, _label, _default in looks.LAYERS})

    def chosen_box(self):
        if not self.use_box.get():
            return None
        try:
            values = [float(self.box[name].get().replace(',', '.')) for name in ('w', 's', 'e', 'n')]
        except ValueError as exc:
            raise ValueError('the box needs four numbers in degrees') from exc
        return timing.validate_box(values)

    def refresh_ready(self):
        if self.place is None:
            return
        slug_id = places.slug(self.place['id'])
        info = country_fetch.availability(slug_id, self.mods.get())
        text = {
            'installed': 'A ready pack is already in mods.',
            'local': 'A ready pack is on disk. It can be copied into mods without a build.',
            'url': 'A link to a ready pack is available.',
            'none': 'No ready pack. Build one from OpenStreetMap and elevation.',
        }[info['state']]
        self.ready.set(f'{self.place["name"]}\n{text}')
        self.download_btn.configure(state=('normal' if not self.running and info['state'] in ('local', 'url') else 'disabled'))
        self._ready = info

    def fetch_size(self, url, place_id):
        try:
            size = country_fetch.content_length(url, timeout=8)
        except Exception as exc:
            self.say(f'could not read the PBF size: {exc}')
            size = None
        self.lines.put(lambda: self.show_size(size, place_id))

    def show_size(self, size, place_id):
        if size:
            self.sizes[place_id] = size
        if self.place and self.place['id'] == place_id:
            label = (f'{size / 2**30:.2f} GB' if size >= 2**30 else f'{size / 2**20:.0f} MB') if size else 'unknown'
            self.size.set(f'Source: {self.place["name"]} · PBF: {label}')
            self.update_estimate()

    def busy(self, running):
        self.running = running
        self.map.enabled = not running
        self.map.city.configure(state='disabled' if running else 'normal')

        def controls(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox)):
                    if running:
                        child._before_busy = child.cget('state')
                        child.configure(state='disabled')
                    else:
                        child.configure(state=getattr(child, '_before_busy', 'normal'))
                controls(child)
        for widget in self.controls:
            controls(widget)
        self.list.configure(state='disabled' if running else 'normal')
        state = 'disabled' if running else 'normal'
        self.build_btn.configure(state=state)
        self.download_btn.configure(state='disabled')
        self.stop_btn.configure(state=('normal' if running else 'disabled'))
        if not running:
            self.progressbar.stop()
            self.refresh_ready()
            self.update_estimate()
        else:
            self.progressbar.start(15)

    def run(self, target, estimate=None, history_key=None):
        if self.running or self.closing:
            return
        try:
            save_settings(self.mods.get())
        except OSError as exc:
            self.say(f'Could not save preferences: {exc}')
        self.cancel = threading.Event()
        self.started = time.monotonic()
        self.active_stage = None
        self.run_estimate = estimate
        self.stage_times = {}
        self.busy(True)

        def wrap():
            result = 'Complete'
            try:
                target()
            except InterruptedError:
                result = 'Stopped'
                self.say('Stopped. Completed source data is kept for the next build.')
            except Exception as exc:
                result = 'Failed'
                self.say(f'stopped: {exc}')
            finally:
                self.lines.put(lambda result=result: self.finished(result, history_key))
        self.worker = threading.Thread(target=wrap, daemon=True)
        self.worker.start()

    def stage_progress(self, name, seconds):
        def update():
            if seconds is None:
                self.active_stage = name
                self.stage_started = time.monotonic()
            else:
                self.stage_times[name] = seconds
        self.lines.put(update)

    def finished(self, result, history_key):
        elapsed = time.monotonic() - self.started
        if result == 'Complete' and history_key and len(self.stage_times) == len(timing.STAGES):
            self.history[history_key] = [self.stage_times[stage] for stage in timing.STAGES]
            try:
                timing.save_history(HISTORY, self.history)
            except OSError as exc:
                self.say(f'Could not save build timing: {exc}')
        self.busy(False)
        self.progress_text.set(f'{result} · {timing.duration(elapsed)} elapsed')

    def download_ready(self):
        if self.place is None:
            return
        info = getattr(self, '_ready', None) or {}
        slug_id = places.slug(self.place['id'])
        mods = self.mods.get()

        def target():
            if self.cancel.is_set():
                raise InterruptedError('install stopped')
            if info.get('state') == 'local':
                path = country_fetch.install_zip(info['path'], mods, slug_id)
            elif info.get('state') == 'url':
                dest = ROOT / 'out' / 'country-setup' / f'earthng_{slug_id}.zip'
                country_fetch.download(info['url'], dest, self.say, self.cancel)
                path = country_fetch.install_zip(dest, mods, slug_id)
            else:
                self.say('no ready pack')
                return
            self.say(f'pack at {path}')
        self.run(target)

    def build(self):
        if self.running:
            return
        if self.place is None:
            messagebox.showinfo('EarthNG', 'Pick a region first.')
            return
        try:
            box = self.chosen_box()
            look = self.chosen_look()
            include = self.chosen_include()
            boundary = self.boundaries.get(self.place['id'])
            if box and boundary is not None:
                from shapely.geometry import box as rectangle
                if not boundary.covers(rectangle(*box)):
                    raise ValueError('This area extends outside the selected source. Use the smallest covering source or select a smaller rectangle.')
        except ValueError as exc:
            messagebox.showerror('EarthNG', str(exc))
            return
        place, mods = self.place, self.mods.get()
        if box and boundary is None:
            self.say('Source boundaries unavailable: coverage could not be checked. Only data in the selected source will be exported.')
        key, estimate, _reason, _cached = self.estimate_inputs()
        block = looks.BLOCK_BY_ID[look['block']]['title']

        def target():
            self.say(f"building “{place['name']}”, block “{block}”. Roads and elevation always go into the pack.")
            self.say('The look is read from earthng_planet.zip. If the planet was built earlier, click “Refresh planet code”.')
            country_fetch.build_place(place, mods, look=look, include=include, box=box,
                                      by_id=self.by_id, emit=self.say, cancel=self.cancel, progress=self.stage_progress)
        self.run(target, estimate=estimate, history_key=key)

    def stop(self):
        if self.running and self.cancel is not None:
            self.cancel.set()
            self.say('stopping after the current step')

    def refresh_planet(self):
        if self.running:
            return
        mods = self.mods.get()
        self.map_version += 1
        if self.map_after:
            self.root.after_cancel(self.map_after)
            self.map_after = None
        # Windows cannot replace an archive held open by the offline map reader.
        # Use coastlines during the update, then reopen the updated map.
        if self.map.data and self.map.data.archive:
            self.map.data.close()
            self.map.data.archive = None
            self.map.data.index = {}
            self.map.schedule()

        def target():
            try:
                country_fetch.refresh_planet(mods, self.say)
            finally:
                self.lines.put(self.reload_map)
        self.run(target)


def main():
    root = tk.Tk()
    Setup(root)
    root.mainloop()


if __name__ == '__main__':
    main()
