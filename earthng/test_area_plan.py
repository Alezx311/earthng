"""Selection regressions for coastal areas, long routes and resumed builds."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import area_plan
import country_fetch
import sections
import selection_build
from shapely.geometry import box, shape

class AreaPlanTests(unittest.TestCase):
    def plan(self, **selection):
        boundaries = {"west": box(0, 0, 1, 1), "east": box(1, 0, 2, 1)}
        entries = {k: {"id": k, "name": k, "parent": "test"} for k in boundaries}
        with patch.object(area_plan, "_near_land", return_value=True):
            return area_plan.plan(boundaries, entries, **selection)

    def test_coastal_box_and_long_route_keep_both_sources(self):
        plan = self.plan(box=[0.1, -0.1, 1.9, 0.9])
        self.assertEqual({p["place"] for p in plan["parts"]}, {"west", "east"})
        self.assertGreater(plan["uncovered_km2"], 0)
        for part in plan["parts"]:
            sections.box(part["section"])
        route = self.plan(route=[[0.1, 0.5], [1.9, 0.5]], width_km=1)
        self.assertEqual({p["place"] for p in route["parts"]}, {"west", "east"})
        self.assertLess(route["km2"], 450)
        for p in route["parts"]:
            self.assertEqual(sections.shape(p["section"]), shape(p["section"]["geometry"]))

    def test_date_line_uses_short_crossing(self):
        corridor = area_plan._corridor(*area_plan.validate_route([[179.8, 0], [-179.8, 0]], 10))
        self.assertLess(area_plan._km2(corridor), 1300)
        self.assertFalse(corridor.intersects(box(-170, -1, 170, 1)))

    def test_invalid_route(self):
        for points in ([], [[0, 0]], [[0, 0], [float("nan"), 0]]):
            with self.assertRaises(ValueError):
                area_plan.validate_route(points)

    def test_stop_resumes_completed_sections_without_overwriting_other_maps(self):
        plan = self.plan(box=[0.1, 0.1, 1.9, 0.9])
        entries = {p["place"]: {"id": p["place"], "name": p["place"]} for p in plan["parts"]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cancel = threading.Event()
            calls = []
            def build(place, mods, **kw):
                calls.append(kw["section"]["id"])
                path = root / "mods" / f'earthng_{place["id"]}_{kw["section"]["id"]}.zip'
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"completed")
                if len(calls) == 1:
                    cancel.set()
                return path
            with patch.object(country_fetch, "_build_place", side_effect=build):
                with self.assertRaises(InterruptedError):
                    selection_build.build(plan, entries, root, root, cancel=cancel)
                cancel.clear()
                paths = selection_build.build(plan, entries, root, root, cancel=cancel)
                self.assertEqual(len(paths), len(plan["parts"]))
                self.assertEqual(len(calls), len(plan["parts"]))
