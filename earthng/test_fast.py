"""Geometry/streaming invariants independent of a BeamNG installation."""
import tempfile
import unittest

import numpy as np
import shapely
from shapely.geometry import Polygon

import fast_profile
import fast_sources as sources


class SourceTests(unittest.TestCase):


    def test_road_width_follows_class_and_implied_oneway(self):
        w = sources.road_width
        self.assertGreater(w({'highway': 'primary'}), w({'highway': 'tertiary'}))
        self.assertGreater(w({'highway': 'tertiary', 'lanes': '2'}), w({'highway': 'unclassified', 'lanes': '1'}))
        # two lanes, implied one-way, shoulders 0.75 + 2.5 m
        self.assertEqual(w({'highway': 'motorway'}), 10.75)
        self.assertEqual(w({'highway': 'trunk', 'lanes': '2', 'oneway': 'yes'}), 9.0)
        self.assertEqual(w({'highway': 'trunk'}), 9.0)                # two lanes, 1 m shoulders
        self.assertEqual(sources.shoulder({'highway': 'trunk', 'oneway': 'yes'}), (.5, 1.5))
        self.assertEqual(sources.shoulder({'highway': 'trunk', 'width': '8'}), (0., 0.))
        # the road register's shoulders (est_roads) win over the class, width tag or not
        self.assertEqual(sources.shoulder({'highway': 'tertiary', 'width': '8', 'shoulder:left:width': '0.5',
                                           'shoulder:right:width': '1'}), (.5, 1.))
        self.assertEqual(w({'highway': 'primary_link', 'oneway': 'yes'}), 4.0)   # lane plus margins
        # lanes=1 on a two-way road: unmarked, both directions share it (Loksa - Hara, 11283)
        self.assertAlmostEqual(w({'highway': 'tertiary', 'lanes': '1'}), 5.4)
        self.assertAlmostEqual(w({'highway': 'residential', 'lanes': '1'}), 5.4)
        self.assertEqual(w({'highway': 'residential'}), 6.0)
        self.assertEqual(w({'highway': 'tertiary', 'lanes': '1', 'oneway': 'yes'}), 4.0)
        ring = w({'highway': 'tertiary', 'junction': 'roundabout'})  # implied one-way, one lane
        self.assertGreaterEqual(ring, 5.5)
        self.assertLess(ring, w({'highway': 'tertiary'}) + 1)
        self.assertEqual(w({'highway': 'trunk', 'junction': 'roundabout', 'lanes': '2'}), 8.0)
        self.assertEqual(w({'highway': 'service', 'service': 'driveway'}), 3.0)
        self.assertEqual(w({'highway': 'residential', 'width': '9'}), 9.0)  # a width tag wins
        self.assertTrue(sources.oneway({'highway': 'motorway'}))
        self.assertFalse(sources.oneway({'highway': 'motorway', 'oneway': 'no'}))
        self.assertFalse(sources.oneway({'highway': 'primary'}))

    def test_dem_missing_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            terrain=sources.Terrain(d)
            with self.assertRaisesRegex(FileNotFoundError,'no_dem'):
                terrain.sample([[0,0]])

    def test_frame_roundtrip_and_negative_tiles(self):
        f=sources.Frame()
        lon,lat=f.geographic(-501,501)
        self.assertEqual(f.tile_of(lon,lat),(-2,1))
        x,y=f.local(lon,lat)
        self.assertAlmostEqual(float(x),-501,places=6)
        self.assertAlmostEqual(float(y),501,places=6)

    def test_frame_at_landing(self):
        # Uzhhorod: zone 34, origin on the point; far from Kyiv's old origin (-613 km)
        f=sources.Frame.at(22.29,48.62)
        self.assertEqual(f.crs,'EPSG:32634')
        x,y=f.local(22.30,48.63)
        self.assertTrue(abs(float(x))<1000 and abs(float(y))<1200)
        g=sources.Frame.of({'frame':f.spec()})
        lon,lat=g.geographic(x,y)
        self.assertAlmostEqual(float(lon),22.30,places=7); self.assertAlmostEqual(float(lat),48.63,places=7)
        self.assertEqual(sources.Frame.of({}).crs,sources.CRS)          # indexes before fast-9

    def test_large_package_is_indexed_as_a_window(self):
        cell=.05
        tiles={f'{x}_{y}':{'cell':[x*cell,y*cell,(x+1)*cell,(y+1)*cell]} for x in range(584,644) for y in range(983,1032)}
        index={'tiles':tiles,'package_box':[29.2,49.15,32.2,51.6]}
        small={'tiles':dict(list(tiles.items())[:50]),'package_box':[0,0,1,1]}
        self.assertIs(sources.window_of(small,(30.5,50.4))[0],small)
        a,wa=sources.window_of(index,(30.36,50.46)); b,wb=sources.window_of(index,(30.31,50.42))
        self.assertEqual(wa,wb)                                  # nearby landings share it
        self.assertEqual(a['centre'],b['centre'])                # and the frame's origin
        self.assertTrue(140<=len(a['tiles'])<=17*11)               # ~ the Kyiv package (162)
        self.assertTrue(wa[0]<30.36-.15 and wa[2]>30.36+.15 and wa[1]<50.46-.1 and wa[3]>50.46+.1)
        with self.assertRaisesRegex(ValueError,'no_osm'):
            sources.window_of(index,(10,10))


    def test_building_walls_face_outwards(self):
        cw=Polygon([(0,0),(0,10),(10,10),(10,0)])                  # clockwise in OSM order
        for poly in shapely.get_parts(shapely.orient_polygons(cw)):
            ring=list(poly.exterior.coords)
            for p,q in zip(ring,ring[1:]):
                quad=np.array([[*p,0],[*q,0],[*q,5]])
                n=np.cross(quad[1]-quad[0],quad[2]-quad[0])
                mid=(np.array(p)+np.array(q))/2
                self.assertGreater(float(n[:2]@(mid-[5,5])),0)


    def test_polylines_match_np_interp_bit_for_bit(self):
        # the index's mouths and junction heights are computed as arrays (write_index): they must
        # equal the per-mouth np.interp they replaced, ends and exact vertices included
        rng=np.random.default_rng(3)
        xp=[np.cumsum(rng.uniform(.01,50,n)) - (5. if n%2 else 0.) for n in rng.integers(2,40,300)]
        fp=[rng.normal(100,30,len(a)) for a in xp]
        k=rng.integers(0,len(xp),5000)
        x=np.array([rng.choice([a[0]-1,a[0],a[-1],a[-1]+1,rng.choice(a),rng.uniform(a[0],a[-1])]) for a in (xp[i] for i in k)])
        lines=sources.Polylines(xp)
        got=lines.value(x,lines.locate(x,k),np.concatenate(fp))
        want=np.array([np.interp(v,xp[i],fp[i]) for v,i in zip(x,k)])
        self.assertTrue(np.array_equal(got,want))


class ProfileTests(unittest.TestCase):
    @staticmethod
    def chain(xs, tags_at=lambda k: {}):
        """Straight road split into segments at xs (shared nodes 1..n)."""
        return [{'xy':[[a,0],[b,0]],'nodes':[k+1,k+2],'tags':tags_at(k)} for k,(a,b) in enumerate(zip(xs,xs[1:]))]

    def test_noisy_flat_dem_gives_gentle_road(self):
        rng=np.random.default_rng(3)
        noise=lambda xy: 40+rng.normal(0,1.5,len(xy))      # 24 m DEM noise floor
        segs=self.chain([0,12,25,31,60,200,215,400])
        prof,_=fast_profile.solve(segs,noise)
        g=max(np.abs(np.diff(h)/np.maximum(np.diff(s),.5)).max() for s,h in prof)
        self.assertLess(g,.06)

    def test_shared_nodes_have_one_height(self):
        segs=self.chain([0,30,90,140])+[{'xy':[[30,0],[30,80]],'nodes':[2,9],'tags':{}}]
        prof,nodes=fast_profile.solve(segs,lambda xy: 40+np.asarray(xy)[:,0]*.03+np.asarray(xy)[:,1]*.05)
        self.assertAlmostEqual(prof[0][1][-1],prof[1][1][0])
        self.assertAlmostEqual(prof[0][1][-1],prof[3][1][0])
        self.assertAlmostEqual(nodes[2],prof[3][1][0])

    def test_building_passage_is_not_a_tunnel(self):
        flat=lambda xy: np.full(len(xy),40.)
        segs=self.chain([0,100,140,240],lambda k:{'tunnel':'building_passage'} if k==1 else {})
        prof,_=fast_profile.solve(segs,flat)
        self.assertLess(max(np.abs(h-40).max() for _,h in prof),1e-3)

    def test_bridge_over_a_valley_ramps_smoothly(self):
        # river valley 12 m deep under a 300 m bridge: no step at the abutments
        valley=lambda xy: 40-12*(np.abs(np.asarray(xy)[:,0]-500)<150)
        segs=self.chain([0,200,350,650,800,1000],lambda k:{'bridge':'yes','layer':'1'} if k==2 else {})
        prof,_=fast_profile.solve(segs,valley)
        s=np.concatenate([p[0]+segs[k]['xy'][0][0] for k,p in enumerate(prof)])
        h=np.concatenate([p[1] for p in prof])
        order=np.argsort(s,kind='stable'); s,h=s[order],h[order]
        keep=np.r_[True,np.diff(s)>.01]; s,h=s[keep],h[keep]
        grade=np.abs(np.diff(h)/np.diff(s))
        self.assertLess(grade.max(),.08)
        mid=h[np.argmin(np.abs(s-500))]
        self.assertGreater(mid,40-12+6)          # the deck stays well above the river

    def test_an_overpass_clears_the_road_under_it(self):
        # Juri: a 51 m trunk bridge over a ring road on flat ground (the DEM has no cutting)
        flat=lambda xy: np.full(len(xy),40.)
        over=self.chain([0,300,325,376,400,700],lambda k:{'bridge':'yes','layer':'1'} if k==2 else {})
        under=[{'xy':[[350,-400],[350,400]],'nodes':[21,22],'tags':{}}]
        prof,_=fast_profile.solve(over+under,flat)
        deck=np.interp(25,prof[2][0],prof[2][1])
        road=np.interp(400,prof[5][0],prof[5][1])
        self.assertGreater(deck-road,fast_profile.CLEARANCE-.15)
        self.assertGreater(deck,42)                       # both move: the deck rises ...
        self.assertLess(road,39)                          # ... the road dips
        for k,(s,h) in enumerate(prof):
            # ramps a car can drive
            self.assertLess(np.abs(np.diff(h)/np.maximum(np.diff(s),.5)).max(),.1,k)
        # a deck already high over a valley road is left where it is (a lower bound)
        valley=lambda xy: 40-12*(np.abs(np.asarray(xy)[:,0]-350)<20)
        free,_=fast_profile.solve(over,valley)
        held,_=fast_profile.solve(over+under,valley)
        self.assertLess(abs(np.interp(25,free[2][0],free[2][1])-np.interp(25,held[2][0],held[2][1])),.05)

    def test_a_road_under_the_bridge_end_is_not_tied_to_the_approach(self):
        # Juri bensiinijaama tee passes 2 m from the end of a 14 m trunk bridge: in plan it
        # touches the trunk's approach, which must not drag the trunk down into the underpass
        flat = lambda xy: np.full(len(xy), 40.)
        over = self.chain([0, 300, 343, 357, 400, 700], lambda k: {'bridge': 'yes', 'layer': '1'} if k == 2 else {})
        under = [{'xy': [[355, -400], [355, 400]], 'nodes': [21, 22], 'tags': {}}]
        prof, _ = fast_profile.solve(over + under, flat)
        deck = np.interp(12, prof[2][0], prof[2][1])
        road = np.interp(400, prof[5][0], prof[5][1])
        self.assertGreater(deck - road, fast_profile.CLEARANCE - .15)
        for k, (s, h) in enumerate(prof):
            self.assertLess(np.abs(np.diff(h) / np.maximum(np.diff(s), .5)).max(), .1, k)

    def test_parallel_carriageways_share_height(self):
        # two oneway halves 12 m apart, 13 m wide (they overlap), over a DEM tilted across them
        dem=lambda xy: 40+np.asarray(xy)[:,1]*.15
        segs=[{'xy':[[0,0],[300,0]],'nodes':[1,2],'tags':{},'width':13.},
              {'xy':[[300,12],[0,12]],'nodes':[3,4],'tags':{},'width':13.}]
        prof,_=fast_profile.solve(segs,dem)
        a=np.interp(150,prof[0][0],prof[0][1]); b=np.interp(150,prof[1][0],prof[1][1])
        self.assertLess(abs(a-b),.05)
        far=[dict(segs[0]),dict(segs[1],xy=[[300,60],[0,60]])]
        prof,_=fast_profile.solve(far,dem)                      # apart: each keeps its ground
        self.assertGreater(abs(np.interp(150,prof[1][0],prof[1][1])-np.interp(150,prof[0][0],prof[0][1])),8)

    def test_station_ids_end_at_nodes(self):
        segs=self.chain([0,7,50,51.5])
        st,ids,pos,seg_of,run,nvar=fast_profile.stations(segs,{1:0,2:1,3:2,4:3})
        for k in range(len(segs)):
            run_ids=ids[seg_of==k]
            self.assertEqual((run_ids[0],run_ids[-1]),(k,k+1))
        self.assertEqual(len(set(ids.tolist())),nvar)


if __name__=='__main__':
    unittest.main()
