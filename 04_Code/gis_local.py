"""Prepared local road/building library. Analysis never requests a network API."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

import geopandas as gpd

LIBRARY = Path(__file__).resolve().parents[1] / '03_Data' / 'beijing_library'


def import_dataset(roads_path, buildings_path, *, roads_layer=None, buildings_layer=None,
                   source_url, coverage, library=LIBRARY, region_name=None,
                   attribution=None, license_url=None):
    """Normalize, validate and atomically publish a new library; never overwrite it."""
    frames, counts = [], []
    for source, layer, types in [(roads_path, roads_layer, ['LineString','MultiLineString']),
                                  (buildings_path, buildings_layer, ['Polygon','MultiPolygon'])]:
        frame = gpd.read_file(source, layer=layer, columns=['name','full_id','osm_id','osm_way_id','id'])
        if frame.crs is None:
            raise ValueError('数据缺少坐标系，不能猜测。')
        frame = frame.to_crs(4326)
        total = len(frame)
        frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty & frame.geometry.is_valid
                          & frame.geom_type.isin(types)].copy()
        if frame.empty:
            raise ValueError('没有有效的道路或建筑物几何。')
        w,s,e,n = frame.total_bounds
        if not (114 <= w <= e <= 120 and 0 <= s <= n <= 84):
            raise ValueError('数据超出当前EPSG:32650投影适用区域。')
        if 'name' not in frame:
            frame['name'] = ''
        frame['name'] = frame['name'].fillna('').astype(str).str.strip()
        if types[0] == 'LineString':
            frame = frame.loc[frame['name'].ne('')].copy()
            if frame.empty:
                raise ValueError('道路数据必须有可用的name名称字段。')
        id_field = next((key for key in ['full_id','osm_id','osm_way_id','id'] if key in frame),None)
        frame['full_id'] = frame[id_field].astype(str) if id_field else frame.index.astype(str)
        frame = frame[['full_id','name','geometry']].reset_index(drop=True)
        # Identifiers may differ for duplicated source geometry: remove only
        # exact name/geometry duplicates, never conflate adjacent buildings.
        frame['_geometry_key'] = frame.geometry.to_wkb(hex=True)
        frame = frame.drop_duplicates(['name','_geometry_key']).drop(columns='_geometry_key')
        counts.append({'source_features':total,'kept_features':len(frame),'excluded_features':total-len(frame)})
        frames.append(frame)
    root = Path(library);root.mkdir(parents=True,exist_ok=True)
    dataset_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix='.import-',dir=root) as staging:
        stage = Path(staging)
        for frame, layer in zip(frames,['roads','buildings']):
            frame.to_file(stage/'data.gpkg',layer=layer,driver='GPKG',SPATIAL_INDEX='YES')
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(stage/'data.gpkg')) as connection:
            connection.execute('CREATE INDEX idx_roads_name ON roads(name)')
            connection.commit()
        metadata = {'dataset_id':dataset_id,'imported_at':datetime.now(timezone.utc).isoformat(),
            'source_url':source_url,'coverage':coverage,'region_name':region_name,
            'attribution':attribution or ('© OpenStreetMap contributors' if 'bbbike' in source_url or 'geofabrik' in source_url else '由数据提供方说明'),
            'license_url':license_url or ('https://www.openstreetmap.org/copyright' if 'bbbike' in source_url or 'geofabrik' in source_url else None),
            'roads':counts[0],'buildings':counts[1],
            'road_bounds_wsen':frames[0].total_bounds.tolist(),'building_bounds_wsen':frames[1].total_bounds.tolist(),
            'source_sha256':{str(Path(x).resolve()):hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in set([roads_path,buildings_path])}}
        metadata['data_sha256'] = hashlib.sha256((stage/'data.gpkg').read_bytes()).hexdigest()
        (stage/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        (stage/'road_names.json').write_text(json.dumps(sorted(frames[0]['name'].unique()),ensure_ascii=False),encoding='utf-8')
        destination = root/dataset_id
        shutil.copytree(stage,destination)
    tmp=root/('active-'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps({'dataset_id':dataset_id}),encoding='utf-8');tmp.replace(root/'active.json')
    return metadata


def active_dataset(library=LIBRARY):
    root=Path(library).resolve()
    active=json.loads((root/'active.json').read_text(encoding='utf-8'))['dataset_id']
    directory=(root/active).resolve()
    if directory.parent != root:
        raise ValueError('数据集路径无效。')
    return directory,json.loads((directory/'metadata.json').read_text(encoding='utf-8'))


def road_candidates(directory,name):
    if not isinstance(name,str) or not 1<=len(name)<=100:
        raise ValueError('道路名称不合法。')
    frame=gpd.read_file(Path(directory)/'data.gpkg',layer='roads',where="name = '"+name.replace("'","''")+"'")
    frame=frame.reset_index(drop=True)
    if frame.empty:return []
    parent=list(range(len(frame)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    left,right=frame.sindex.query(frame.geometry,predicate='intersects')
    for i,j in zip(left,right):parent[find(int(i))]=find(int(j))
    groups={}
    for i in range(len(frame)):groups.setdefault(find(i),[]).append(i)
    return [frame.iloc[indexes].copy() for indexes in groups.values()]


def prepare_analysis(directory,roads,radius,destination):
    if not 0<float(radius)<=5000 or roads.empty:
        raise ValueError('请选择有效道路与0至5000米（不含0）的距离。')
    buffer=roads.to_crs(32650).geometry.union_all().buffer(float(radius)+100)
    bbox=gpd.GeoSeries([buffer],crs=32650).to_crs(4326).total_bounds
    buildings=gpd.read_file(Path(directory)/'data.gpkg',layer='buildings',bbox=tuple(bbox))
    if buildings.empty:
        raise ValueError('该范围没有可用建筑物记录。可能是数据覆盖不足，不能判定没有建筑物。')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    roads.to_file(destination/'target_road.geojson',driver='GeoJSON')
    buildings.to_file(destination/'buildings_osm.geojson',driver='GeoJSON')
    metadata=json.loads((Path(directory)/'metadata.json').read_text(encoding='utf-8'))
    return {'dataset_id':metadata['dataset_id'],'source_url':metadata['source_url'],
        'attribution':metadata['attribution'],'license_url':metadata['license_url'],
        'imported_at':metadata['imported_at'],'data_sha256':metadata['data_sha256'],
        'road_ids':roads['full_id'].tolist(),'query_bbox_wsen':bbox.tolist(),
        'dataset_coverage':metadata['coverage'],
        'coverage':'本地数据包内有效建筑物，按所选路段缓冲区加100米的包围框读取；不代表行政区全量建筑普查。占比和范围外数量仅针对本次读取样本。'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='一次导入北京道路与建筑物，之后离线筛选')
    parser.add_argument('--roads',required=True);parser.add_argument('--buildings',required=True)
    parser.add_argument('--roads-layer');parser.add_argument('--buildings-layer')
    parser.add_argument('--source-url',required=True);parser.add_argument('--coverage',required=True)
    args=parser.parse_args()
    print(json.dumps(import_dataset(args.roads,args.buildings,roads_layer=args.roads_layer,
        buildings_layer=args.buildings_layer,source_url=args.source_url,coverage=args.coverage),ensure_ascii=True,indent=2))
