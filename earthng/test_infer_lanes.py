"""Lanes carried over to the untagged sections of a road (fast_sources.infer_lanes)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_sources as fs

KEY = fs.LANES_KEY
STEP = 0.01     # degrees of longitude a way: ~715 m at 50 N


def chain(tags_list, start=1, lon=30.0, lat=50.0, step=STEP):
    """Ways end to end along a parallel: {id: (tags, [(node, lon, lat), (node, lon, lat)])}."""
    roads = {}
    for k, tags in enumerate(tags_list):
        a, b = start * 1000 + k, start * 1000 + k + 1
        roads[start * 100 + k] = (dict(tags), [(a, lon + k * step, lat), (b, lon + (k + 1) * step, lat)])
    return roads


def lanes(roads):
    return [roads[w][0].get(KEY) for w in sorted(roads)]


class InferLanesTests(unittest.TestCase):
    def test_a_gap_between_two_tagged_stretches_takes_their_lanes(self):
        road = {'highway': 'primary', 'name': 'Проспект'}
        roads = chain([{**road, 'lanes': '4'}, road, road, {**road, 'lanes': '4'}])
        self.assertEqual(fs.infer_lanes(roads), 2)
        self.assertEqual(lanes(roads), [None, '4', '4', None])
        # the mapper's own tags are not touched
        self.assertEqual(roads[100][0]['lanes'], '4')

    def test_the_fewer_lanes_win_where_the_ends_differ(self):
        road = {'highway': 'secondary', 'ref': 'T-10-01'}
        roads = chain([{**road, 'lanes': '6'}, road, {**road, 'lanes:forward': '2', 'lanes:backward': '2'}])
        fs.infer_lanes(roads)
        self.assertEqual(lanes(roads), [None, '4', None])

    def test_a_long_untagged_road_keeps_its_default(self):
        road = {'highway': 'primary', 'name': 'Траса'}
        # ~715 m a way: five untagged ways are over LANE_GAP
        roads = chain([{**road, 'lanes': '4'}] + [road] * 5 + [{**road, 'lanes': '4'}])
        self.assertEqual(fs.infer_lanes(roads), 0)
        self.assertEqual(lanes(roads), [None] * 7)

    def test_a_short_tail_takes_the_lanes_before_it_and_a_long_one_does_not(self):
        road = {'highway': 'tertiary', 'name': 'Вулиця'}
        short = chain([{**road, 'lanes': '4'}, road], step=0.004)        # ~285 m
        fs.infer_lanes(short)
        self.assertEqual(lanes(short), [None, '4'])
        long = chain([{**road, 'lanes': '4'}, road])                     # ~715 m
        fs.infer_lanes(long)
        self.assertEqual(lanes(long), [None, None])

    def test_only_the_same_road_passes_its_lanes_on(self):
        a = {'highway': 'primary', 'name': 'Перша', 'lanes': '4'}
        for other in ({'highway': 'primary', 'name': 'Друга'},                       # another street
                      {'highway': 'secondary', 'name': 'Перша'},                     # another class
                      {'highway': 'primary', 'name': 'Перша', 'oneway': 'yes'},      # a carriageway of its own
                      {'highway': 'primary'},                                        # no name to go by
                      {'highway': 'primary', 'name': 'Перша', 'junction': 'roundabout'}):
            roads = chain([a, other, a], step=0.002)
            fs.infer_lanes(roads)
            self.assertIn(roads[101][0].get(KEY), (None, '2'), other)
            self.assertNotEqual(roads[101][0].get(KEY), '4', other)

    def test_a_fork_stops_the_line(self):
        road = {'highway': 'residential', 'name': 'Розвилка'}
        roads = chain([{**road, 'lanes': '4'}, road, {**road, 'lanes': '4'}], step=0.002)
        # a third way of the same street ends at the node between the first two
        roads[900] = (dict(road), [(1001, 30.002, 50.0), (9001, 30.002, 50.002)])
        fs.infer_lanes(roads)
        # the middle way is reached only from its far end now: a tail, short enough
        self.assertEqual(roads[101][0].get(KEY), '4')
        self.assertIsNone(roads[900][0].get(KEY))

    def test_a_ring_of_one_street_does_not_loop(self):
        road = {'highway': 'residential', 'name': 'Кільцева'}
        roads = {1: ({**road, 'lanes': '2'}, [(1, 30.0, 50.0), (2, 30.001, 50.0)]),
                 2: (dict(road), [(2, 30.001, 50.0), (3, 30.001, 50.001)]),
                 3: (dict(road), [(3, 30.001, 50.001), (1, 30.0, 50.0)])}
        fs.infer_lanes(roads)
        self.assertEqual([roads[w][0].get(KEY) for w in (2, 3)], ['2', '2'])

    def test_an_untagged_carriageway_of_a_main_road_is_two_lanes(self):
        roads = chain([{'highway': 'trunk', 'oneway': 'yes'}, {'highway': 'primary', 'oneway': 'yes'},
                       {'highway': 'secondary', 'oneway': 'yes'}, {'highway': 'primary'},
                       {'highway': 'primary', 'oneway': 'yes', 'lanes': '1'},
                       {'highway': 'primary', 'junction': 'roundabout'}, {'highway': 'trunk_link', 'oneway': 'yes'}])
        fs.infer_lanes(roads)
        self.assertEqual(lanes(roads), ['2', '2', None, None, None, None, None])

    def test_the_width_follows_the_carried_lanes_but_a_tag_wins(self):
        base = {'highway': 'primary', 'oneway': 'yes'}
        one = fs.road_width(base)
        self.assertEqual(one, 4.0 + .25 + .75)                              # a single lane and its shoulders
        self.assertEqual(fs.road_width({**base, KEY: '3'}), 3 * 3.5 + .25 + .75)
        self.assertEqual(fs.road_width({**base, KEY: '3', 'lanes': '2'}), 2 * 3.5 + .25 + .75)
        self.assertEqual(fs.road_width({**base, KEY: '3', 'width': '9'}), 9.0)
        two = {'highway': 'secondary', 'name': 'x'}
        self.assertEqual(fs.road_width({**two, KEY: '4'}), 4 * 3.25 + .5)

    def test_the_result_does_not_depend_on_the_order_of_the_ways(self):
        road = {'highway': 'primary', 'name': 'Проспект'}
        tags = [{**road, 'lanes': '6'}, road, road, {**road, 'lanes': '4'}, road, {**road, 'lanes': '2'}]
        first = chain(tags, step=0.003)
        fs.infer_lanes(first)
        second = dict(reversed(list(chain(tags, step=0.003).items())))
        fs.infer_lanes(second)
        self.assertEqual(lanes(first), lanes(second))
        self.assertEqual(lanes(first), [None, '4', '4', None, '2', None])


if __name__ == '__main__':
    unittest.main()
