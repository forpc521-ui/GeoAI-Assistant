from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import geopandas as gpd
from shapely.geometry import LineString,box
from gis_local import import_dataset,active_dataset,road_candidates,prepare_analysis
from gis_natural import BufferTask
from gis_history import save_run,reproduce_run


class LocalDatasetTests(unittest.TestCase):
    def test_regional_names_do_not_match_distance_digits_or_substrings(self):
        from gis_natural import parse_task
        roads=['5','村大街','中关村大街','学院路']
        task=parse_task('分析中关村大街周边500米范围内的建筑物',roads)
        self.assertEqual(task.road_name,'中关村大街')
        with self.assertRaises(ValueError):
            parse_task('分析中关村大街周边500米范围内的建筑物，另分析学院路',roads)

    def test_jiaoda_screenshot_query_with_numeric_road_names(self):
        from gis_natural import parse_task
        names=['5','500','东路','交大东路','学院路']
        task=parse_task('分析交大东路周围500m范围的建筑物',names)
        self.assertEqual(task.road_name,'交大东路')
        self.assertEqual(task.distance_m,500)
        with self.assertRaises(ValueError):
            parse_task('分析交大东路周围500m范围的建筑物，计算平均高度',names)

    def sources(self,root):
        roads=gpd.GeoDataFrame({'name':["测试'路","测试'路",'同名路','同名路'],'full_id':['a','b','c','d']},
            geometry=[LineString([(116.3,39.9),(116.3,39.901)]),LineString([(116.3,39.901),(116.3,39.902)]),
                      LineString([(116.4,39.9),(116.4,39.901)]),LineString([(116.5,39.9),(116.5,39.901)])],crs=4326)
        buildings=gpd.GeoDataFrame({'full_id':['one','two']},geometry=[box(116.3001,39.9,116.3002,39.9001),box(116.6,39.9,116.601,39.901)],crs=4326)
        rp=root/'roads.geojson';bp=root/'buildings.geojson'
        roads.to_file(rp);buildings.to_file(bp)
        return rp,bp

    def test_import_search_spatial_subset_and_replay_without_network(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden')):
            root=Path(tmp);rp,bp=self.sources(root)
            m=import_dataset(rp,bp,source_url='fixture',coverage='测试数据，不是北京市数据',library=root/'library')
            directory,metadata=active_dataset(root/'library')
            self.assertEqual(metadata['roads']['kept_features'],4)
            self.assertEqual(len(road_candidates(directory,'同名路')),2)
            candidates=road_candidates(directory,"测试'路")
            self.assertEqual(len(candidates),1);self.assertEqual(len(candidates[0]),2)
            source=prepare_analysis(directory,candidates[0],300,root/'inputs')
            b=gpd.read_file(root/'inputs/buildings_osm.geojson');self.assertEqual(len(b),1)
            record=save_run(BufferTask("测试'路",300),'fixture','本地道路',root/'inputs',history_dir=root/'history',dataset_metadata=source)
            self.assertEqual(record['statistics']['buildings_intersect'],1)
            replay=reproduce_run(record['task_id'],root/'history')
            self.assertTrue(replay['reproduction']['matches'])
            self.assertEqual(replay['dataset_source'],source)

    def test_failed_import_preserves_active_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rp,bp=self.sources(root);library=root/'library'
            first=import_dataset(rp,bp,source_url='fixture',coverage='test',library=library)
            bad=gpd.read_file(rp);bad['name']='';bad.to_file(root/'bad.geojson')
            with self.assertRaises(ValueError):import_dataset(root/'bad.geojson',bp,source_url='fixture',coverage='test',library=library)
            self.assertEqual(active_dataset(library)[1]['dataset_id'],first['dataset_id'])

    def test_no_matches_or_coverage_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rp,bp=self.sources(root)
            import_dataset(rp,bp,source_url='fixture',coverage='partial',library=root/'library')
            directory,_=active_dataset(root/'library')
            self.assertEqual(road_candidates(directory,'不存在'),[])
            with self.assertRaisesRegex(ValueError,'覆盖不足'):
                prepare_analysis(directory,road_candidates(directory,'同名路')[0],1,root/'output')
            with self.assertRaises(ValueError):prepare_analysis(directory,road_candidates(directory,"测试'路")[0],float('nan'),root/'output')


if __name__=='__main__':unittest.main()
