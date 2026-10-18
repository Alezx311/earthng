"""Tk region picker. Reuses the planet's offline Natural Earth map, no web tiles."""
import io
import json
import math
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import zipfile

from PIL import Image, ImageTk

MAX_LAT = 85.05112878


def project(lon, lat):
    lat = math.radians(max(-MAX_LAT, min(MAX_LAT, lat)))
    return (lon + 180) / 360, (1 - math.asinh(math.tan(lat)) / math.pi) / 2


def unproject(x, y):
    return max(-180, min(180, x * 360 - 180)), math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * max(0, min(1, y))))))


class MapData:
    def __init__(self, root, mods):
        self.directory = Path(root) / 'out' / 'basemap' / '3'
        self.archive = None
        self.index = {}
        self.labels = []
        self.coast = json.loads((Path(root) / 'mod/earthng/planet/coastline.json').read_text())
        try:
            if not (self.directory / 'index.json').exists():
                self.archive = zipfile.ZipFile(Path(mods) / 'mods' / 'earthng_planet.zip')
            self.index = json.loads(self.read('index.json'))
            self.labels = json.loads(self.read('labels.json')).get('places', [])
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self.index = {}

    def read(self, name):
        if self.archive:
            return self.archive.read('earthng/planet/basemap/' + name)
        return (self.directory / name).read_bytes()

    @lru_cache(maxsize=96)
    def tile(self, key):
        name = self.index.get('tiles', {}).get(key)
        if name:
            try:
                with Image.open(io.BytesIO(self.read(f't/{name}.png'))) as image:
                    return image.convert('RGB')
            except (OSError, KeyError):
                pass
        return None

    def close(self):
        self.tile.cache_clear()
        if self.archive:
            self.archive.close()


class RegionMap(ttk.Frame):
    def __init__(self, parent, on_box):
        super().__init__(parent)
        self.on_box = on_box
        self.data = None
        self.boundary = None
        self.selection = None
        self.center = project(30.5, 50.45)
        self.zoom = 4
        self.pending = None
        self.enabled = True
        self.drag = None
        self.photos = []
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        self.mode = tk.StringVar(value='pan')
        ttk.Radiobutton(bar, text='Move map', variable=self.mode, value='pan').pack(side='left')
        ttk.Radiobutton(bar, text='Select area', variable=self.mode, value='select').pack(side='left')
        ttk.Button(bar, text='+', width=3, command=lambda: self.change_zoom(1)).pack(side='left', padx=3)
        ttk.Button(bar, text='−', width=3, command=lambda: self.change_zoom(-1)).pack(side='left')
        ttk.Button(bar, text='Fit source', command=self.fit_source).pack(side='left', padx=3)
        self.canvas = tk.Canvas(self, background='#aad3df', highlightthickness=0, height=340)
        self.canvas.pack(fill='both', expand=True, pady=4)
        self.canvas.bind('<Configure>', lambda _: self.schedule())
        self.canvas.bind('<MouseWheel>', lambda e: self.change_zoom(1 if e.delta > 0 else -1, e.x, e.y))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.hint = tk.StringVar(value='Drag to move. Select area → drag a rectangle. Wheel to zoom.')
        ttk.Label(self, textvariable=self.hint, wraplength=600).pack(anchor='w')
        ttk.Label(self, text='Natural Earth • offline regional map (no street detail)', foreground='#666').pack(anchor='w')
        search = ttk.Frame(self)
        search.pack(fill='x', pady=4)
        ttk.Label(search, text='Find city').pack(side='left')
        self.city = ttk.Combobox(search)
        self.city.pack(side='left', fill='x', expand=True, padx=6)
        self.city.bind('<KeyRelease>', self.find_cities)
        self.city.bind('<<ComboboxSelected>>', self.go_city)
        self.city.bind('<Return>', self.go_city)
        self.city_matches = {}

    def find_cities(self, _event=None):
        needle = self.city.get().casefold().strip()
        matches = [row for row in (self.data.labels if self.data else [])
                   if needle and (needle in row[3].casefold() or needle in row[4].casefold())][:30]
        self.city_matches = {f'{r[3]} / {r[4]} ({r[0]:.2f}, {r[1]:.2f})': r for r in matches}
        self.city.configure(values=list(self.city_matches))

    def go_city(self, _event=None):
        if not self.enabled:
            return
        row = self.city_matches.get(self.city.get()) or next(iter(self.city_matches.values()), None)
        if row:
            self.center, self.zoom = project(row[1], row[0]), 10
            self.schedule()

    def xy(self, lon, lat):
        x, y = project(lon, lat)
        scale = 256 * 2 ** self.zoom
        return ((x - self.center[0]) * scale + self.canvas.winfo_width() / 2,
                (y - self.center[1]) * scale + self.canvas.winfo_height() / 2)

    def geo(self, x, y):
        scale = 256 * 2 ** self.zoom
        return unproject(self.center[0] + (x - self.canvas.winfo_width() / 2) / scale,
                         self.center[1] + (y - self.canvas.winfo_height() / 2) / scale)

    def fit_source(self):
        if self.boundary is not None:
            self.fit(self.boundary.bounds)

    def fit(self, box):
        w, s, e, n = box
        x0, y0 = project(w, n)
        x1, y1 = project(e, s)
        self.center = ((x0 + x1) / 2, (y0 + y1) / 2)
        width, height = max(200, self.canvas.winfo_width() - 40), max(160, self.canvas.winfo_height() - 40)
        self.zoom = max(1, min(14, math.floor(math.log2(min(width / max(1e-9, x1-x0), height / max(1e-9, y1-y0)) / 256))))
        self.schedule()

    def change_zoom(self, delta, x=None, y=None):
        if x is None:
            x, y = self.canvas.winfo_width()/2, self.canvas.winfo_height()/2
        before = project(*self.geo(x, y))
        self.zoom = max(1, min(14, self.zoom + delta))
        scale = 256 * 2 ** self.zoom
        self.center = (before[0] - (x-self.canvas.winfo_width()/2)/scale,
                       before[1] - (y-self.canvas.winfo_height()/2)/scale)
        self.schedule()

    def press(self, event):
        if self.enabled:
            self.drag = (event.x, event.y, self.center, self.mode.get())

    def motion(self, event):
        if not self.drag:
            return
        x, y, center, mode = self.drag
        if mode == 'pan':
            scale = 256 * 2 ** self.zoom
            self.center = tuple(max(0, min(1, v)) for v in
                                (center[0]-(event.x-x)/scale, center[1]-(event.y-y)/scale))
            self.schedule()
        else:
            self.canvas.delete('drag')
            self.canvas.create_rectangle(x, y, event.x, event.y, outline='#176ec1', width=3, tags='drag')

    def release(self, event):
        if not self.drag:
            return
        x, y, _center, mode = self.drag
        self.drag = None
        self.canvas.delete('drag')
        if mode == 'select' and abs(event.x-x) >= 4 and abs(event.y-y) >= 4:
            a, b = self.geo(x, y), self.geo(event.x, event.y)
            box = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
            self.on_box(box)

    def schedule(self):
        if self.pending is None:
            self.pending = self.after(30, self.draw)

    def draw(self):
        self.pending = None
        c = self.canvas
        c.delete('all')
        self.photos = []
        width, height = c.winfo_width(), c.winfo_height()
        if self.data and self.data.index:
            # Enlarge the highest local tile for city-scale selection; never fetch remote tiles.
            z = min(self.zoom, self.data.index['maxZoom'])
            size = 256 * 2 ** (self.zoom-z)
            ox, oy = self.center[0]*2**z*size-width/2, self.center[1]*2**z*size-height/2
            for x in range(max(0, math.floor(ox/size)), min(2**z, math.ceil((ox+width)/size))):
                for y in range(max(0, math.floor(oy/size)), min(2**z, math.ceil((oy+height)/size))):
                    tile = self.data.tile(f'{z}/{x}/{y}')
                    if tile:
                        # Crop before resizing: zoom 14 must not allocate a 16384² bitmap.
                        left, top = x*size-ox, y*size-oy
                        dx, dy = max(0, left), max(0, top)
                        dw, dh = min(width, left+size)-dx, min(height, top+size)-dy
                        crop = ((dx-left)*256/size, (dy-top)*256/size,
                                (dx+dw-left)*256/size, (dy+dh-top)*256/size)
                        rendered = tile.transform((max(1, math.ceil(dw)), max(1, math.ceil(dh))), Image.Transform.EXTENT, crop)
                        photo = ImageTk.PhotoImage(rendered)
                        self.photos.append(photo)
                        c.create_image(dx, dy, image=photo, anchor='nw')
        elif self.data:
            for ring in self.data.coast:
                points = [v for lon, lat in ring for v in self.xy(lon, lat)]
                if len(points) >= 6:
                    c.create_polygon(points, fill='#f2efe9', outline='#9aafa6')
        if self.data:
            for row in self.data.labels:
                lat, lon, minzoom, label = row[:4]
                if self.zoom < minzoom + 1:
                    continue
                x, y = self.xy(lon, lat)
                if 0 < x < width and 0 < y < height:
                    c.create_oval(x-2, y-2, x+2, y+2, fill='#445461', outline='')
                    c.create_text(x+5, y, text=label, anchor='w', fill='#273640', font=('Segoe UI', 9))
        if self.boundary is not None:
            polygons = list(self.boundary.geoms) if self.boundary.geom_type == 'MultiPolygon' else [self.boundary]
            for polygon in polygons:
                if polygon.geom_type != 'Polygon':
                    continue
                for ring in (polygon.exterior, *polygon.interiors):
                    coords = list(ring.coords)
                    step = max(1, len(coords)//1500)
                    points = [v for lon, lat in coords[::step] + [coords[-1]] for v in self.xy(lon, lat)]
                    if len(points) >= 4:
                        c.create_line(points, fill='#8153a4', width=2)
        if self.selection:
            w, s, e, n = self.selection
            c.create_rectangle(*self.xy(w, n), *self.xy(e, s), outline='#086ec5', width=3,
                               fill='#338bca', stipple='gray12')
