import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gis_online import search_roads, fetch_inputs, buildings_frame, OnlineDataError, request_osm
from gis_history import save_run, reproduce_run, export_record
from gis_natural import BufferTask


def way(i, points, tags=None, nodes=None):
    return {'type': 'way', 'id': i, 'nodes': nodes or [i*10, i*10+1],
            'tags': tags or {'name': '测试路', 'highway': 'residential'},
            'geometry': [{'lon': x, 'lat': y} for x, y in points]}


def response(elements):
    return {'payload': {'elements': elements, 'osm3s': {'timestamp_osm_base': '2026-11-10T00:00:00Z'}},
            'endpoint': 'fixture', 'retrieved_at': '2026-11-10T00:00:00Z', 'query': 'fixture', 'response_sha256': 'fixture'}


class OnlineTests(unittest.TestCase):
    def candidate(self):
        return search_roads('测试路', lambda q: response([
            way(1, [(116.3,39.9),(116.3,39.901)], nodes=[1,2]),
            way(2, [(116.3,39.901),(116.3,39.902)], nodes=[2,3])]))

    def test_disconnected_same_name_not_merged(self):
        c,_=search_roads('测试路', lambda q: response([
            way(1,[(116.3,39.9),(116.3,39.901)],nodes=[1,2]),
            way(2,[(116.3,39.901),(116.3,39.902)],nodes=[2,3]),
            way(3,[(116.4,39.9),(116.4,39.901)])]))
        self.assertEqual([x['way_ids'] for x in c], [[1,2],[3]])

    def test_search_escaping_and_no_match(self):
        queries=[]
        self.assertEqual(search_roads('不存在"路',lambda q: queries.append(q) or response([]))[0],[])
        self.assertIn('name"='+json.dumps('不存在"路',ensure_ascii=False),queries[0])
        for name in ['', '路\n名', '路'*61]:
            with self.assertRaises(OnlineDataError):search_roads(name)

    def test_geometry_relations_holes_and_invalid(self):
        outer=[(116.3,39.9),(116.301,39.9),(116.301,39.901),(116.3,39.901),(116.3,39.9)]
        inner=[(116.3002,39.9002),(116.3008,39.9002),(116.3008,39.9008),(116.3002,39.9008),(116.3002,39.9002)]
        r={'type':'relation','id':8,'tags':{'building':'yes'},'members':[
            {'type':'way','ref':1,'role':'outer','geometry':way(1,outer)['geometry']},
            {'type':'way','ref':2,'role':'inner','geometry':way(2,inner)['geometry']}]}
        b,skipped=buildings_frame([r,way(1,outer,{'building':'yes'}),way(9,outer[:3],{'building':'yes'})])
        self.assertEqual(len(b),1);self.assertEqual(skipped,1)
        self.assertEqual(len(b.geometry.iloc[0].interiors),1)

    def test_online_snapshot_export_and_replay_without_network(self):
        c,source=self.candidate()
        building=way(9,[(116.3001,39.9),(116.3002,39.9),(116.3002,39.9001),(116.3001,39.9001),(116.3001,39.9)],{'building':'yes'})
        with tempfile.TemporaryDirectory() as root:
            inputs=Path(root)/'inputs';history=Path(root)/'history'
            metadata=fetch_inputs(c[0],300,inputs,lambda q:response([building]),source)
            record=save_run(BufferTask('测试路',300),'测试','在线OSM路段选择',inputs,history_dir=history,source_metadata=metadata)
            self.assertEqual(record['statistics']['buildings_intersect'],1)
            self.assertIn('online_source',record)
            with patch('gis_online.request_osm',side_effect=AssertionError('Network during replay')):
                replay=reproduce_run(record['task_id'],history)
            self.assertTrue(replay['reproduction']['matches'])
            self.assertEqual(replay['online_source'],metadata)
            self.assertGreater(len(export_record(record['task_id'],history)),0)

    def test_empty_data_and_distance_rejected(self):
        c,_=self.candidate()
        with tempfile.TemporaryDirectory() as root:
            for radius in [0,1001,float('nan')]:
                with self.assertRaises(OnlineDataError):fetch_inputs(c[0],radius,root)
            with self.assertRaises(OnlineDataError):fetch_inputs(c[0],300,root,lambda q:response([]))
            self.assertFalse((Path(root)/'target_road.geojson').exists())

    def test_network_failures_and_partial_payload_never_cached(self):
        with tempfile.TemporaryDirectory() as root, patch('gis_online.CACHE',Path(root)), patch('gis_online.time.sleep'):
            with patch('urllib.request.urlopen',side_effect=TimeoutError):
                with self.assertRaises(OnlineDataError):request_osm('timeout fixture')
            from unittest.mock import MagicMock
            result=MagicMock();result.__enter__.return_value.read.return_value=b'{"remark":"timeout","elements":[]}'
            with patch('urllib.request.urlopen',return_value=result):
                with self.assertRaises(OnlineDataError):request_osm('partial fixture')
            self.assertEqual(list(Path(root).glob('*.json')),[])

    def test_gateway_error_is_not_reported_as_timeout(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as root, patch('gis_online.CACHE',Path(root)), patch('gis_online.time.sleep'):
            with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('fixture',502,'Bad Gateway',{},None)):
                with self.assertRaisesRegex(OnlineDataError,'HTTP 502'):
                    request_osm('gateway fixture')

    def test_direct_request_uses_local_opener_and_probe_bypasses_cache(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as root, patch('gis_online.CACHE',Path(root)), patch('gis_online.time.sleep'):
            opener=MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value=b'{"elements":[]}'
            with patch('urllib.request.build_opener',return_value=opener), patch('urllib.request.urlopen') as system:
                request_osm('direct fixture',proxy_mode='direct',timeout=10,use_cache=False)
                system.assert_not_called()
                self.assertEqual(opener.open.call_args.kwargs['timeout'],10)
                self.assertEqual(list(Path(root).glob('*.json')),[])


if __name__=='__main__':unittest.main()
