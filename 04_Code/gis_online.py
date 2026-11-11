"""Bounded, cached OpenStreetMap retrieval for Beijing road segments.

No model calls, uploads, credentials or fabricated fallback data.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl

import geopandas as gpd
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

ENDPOINT = os.environ.get('OVERPASS_API_URL', 'https://overpass-api.de/api/interpreter')
CACHE = Path(__file__).resolve().parents[1] / '03_Data' / 'online_cache'
LOCK = threading.Lock()
LAST_REQUEST = 0.0


class OnlineDataError(ValueError):
    pass


def request_osm(query, endpoint=None, proxy_mode='system', timeout=40, use_cache=True):
    """One serialized request, no automatic retries, one-hour persistent cache."""
    global LAST_REQUEST
    endpoint = endpoint or ENDPOINT
    if not endpoint.startswith('https://'):
        raise OnlineDataError('数据服务地址必须使用HTTPS。')
    if proxy_mode not in ('system', 'direct'):
        raise OnlineDataError('不支持的网络连接方式。')
    digest = hashlib.sha256((endpoint + '\n' + query).encode()).hexdigest()
    with LOCK:
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / (digest + '.json')
        if use_cache and path.exists() and time.time() - path.stat().st_mtime < 3600:
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        time.sleep(max(0, 2 - (time.monotonic() - LAST_REQUEST)))
        req = urllib.request.Request(endpoint,
            data=urllib.parse.urlencode({'data': query}).encode(),
            headers={'User-Agent': 'GeoAI-Assistant/1.0 (https://github.com/forpc521-ui/GeoAI-Assistant)',
                     'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            LAST_REQUEST = time.monotonic()
            # Direct mode affects only this request, never system proxy settings.
            open_request = (urllib.request.urlopen if proxy_mode == 'system' else
                            urllib.request.build_opener(urllib.request.ProxyHandler({})).open)
            with open_request(req, timeout=timeout) as response:
                raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise OnlineDataError('在线数据超过20MB限制，请缩小分析范围。')
            payload = json.loads(raw)
            if payload.get('remark') or not isinstance(payload.get('elements'), list):
                raise OnlineDataError('数据服务未完整完成查询，请稍后重试，不使用部分结果。')
        except OnlineDataError:
            raise
        except urllib.error.HTTPError as exc:
            hints = {429: '服务限流，请稍后重试', 502: '数据服务网关异常，可手动切换服务',
                     503: '服务暂不可用，可稍后重试或手动切换服务',
                     504: '服务端计算或网关超时，可缩小范围或手动切换服务',
                     403: '访问被拒绝，请检查代理或服务访问限制'}
            raise OnlineDataError(f"在线服务 HTTP {exc.code}：{hints.get(exc.code, '服务请求失败，请先检测连接')}。") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            reason = getattr(exc, 'reason', exc)
            if isinstance(reason, ssl.SSLError):
                message = 'HTTPS证书或握手失败，请检查网络环境和证书配置，不要关闭证书验证。'
            elif isinstance(reason, TimeoutError):
                mode = '系统代理' if proxy_mode == 'system' else '直连'
                message = f'{mode}请求在{timeout}秒内未取得完整响应。请先检测连接；若微型检测也超时，扩大查询等待时间通常无效。'
            else:
                message = '连接数据服务失败，请检查网络、域名解析和代理；可使用页面连接检测定位。'
            raise OnlineDataError(message) from exc
        except Exception as exc:
            raise OnlineDataError('无法获取在线数据：服务可能超时、限流或网络不可达。请稍后手动重试。') from exc
        result = {'payload': payload, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'endpoint': endpoint, 'query': query, 'response_sha256': hashlib.sha256(raw).hexdigest()}
        if not use_cache:
            return result
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
        for old in sorted(CACHE.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[128:]:
            old.unlink(missing_ok=True)
        return result


def search_roads(name, requester=request_osm):
    name = name.strip()
    if not 1 <= len(name) <= 60 or any(ord(c) < 32 for c in name):
        raise OnlineDataError('请输入1至60字的完整道路名称，不含控制字符。')
    literal = json.dumps(name, ensure_ascii=False)
    query = f'[out:json][timeout:25];area["ISO3166-2"="CN-BJ"]["boundary"="administrative"]->.bj;way(area.bj)["highway"]["name"={literal}];out geom;'
    fetched = requester(query)
    ways = [e for e in fetched['payload']['elements'] if e.get('type') == 'way'
            and e.get('tags', {}).get('name') == name and len(e.get('geometry', [])) > 1]
    if len(ways) > 2000:
        raise OnlineDataError('道路要素过多，请使用更具体的道路名称。')
    # Shared OSM nodes connect fragments; disconnected and parallel ways stay
    # separate candidates instead of merging all identically named roads.
    parent = list(range(len(ways)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, way in enumerate(ways):
        for node in way.get('nodes', []):
            if node in seen:
                parent[find(i)] = find(seen[node])
            seen[node] = i
    groups = {}
    for i, way in enumerate(ways):
        groups.setdefault(find(i), []).append(way)
    candidates = []
    for elements in groups.values():
        frame = roads_frame(elements, name)
        west, south, east, north = frame.total_bounds
        if not (115 <= west <= east <= 118 and 39 <= south <= north <= 42):
            continue
        candidates.append({'name': name, 'elements': elements,
            'way_ids': sorted(e['id'] for e in elements),
            'bbox': [float(west), float(south), float(east), float(north)],
            'length_m': float(frame.to_crs(32650).length.sum())})
    return candidates, fetched


def roads_frame(elements, name):
    return gpd.GeoDataFrame([{'name': name, 'full_id': f"w{e['id']}",
        'geometry': LineString([(p['lon'], p['lat']) for p in e['geometry']])}
        for e in elements], crs=4326)


def buildings_frame(elements):
    rows, skipped, relation_members = [], 0, set()
    for e in elements:
        if e.get('type') != 'relation' or not e.get('tags', {}).get('building'):
            continue
        try:
            members = e.get('members', [])
            outer, inner = [], []
            for m in members:
                if m.get('type') != 'way' or len(m.get('geometry', [])) < 2:
                    continue
                points = [(p['lon'], p['lat']) for p in m['geometry']]
                (inner if m.get('role') == 'inner' else outer).append(LineString(points))
            polygons = list(polygonize(outer))
            if not polygons:
                raise ValueError('No closed outer geometry')
            geom = unary_union(polygons)
            holes = list(polygonize(inner))
            if holes:
                geom = geom.difference(unary_union(holes))
            if geom.is_empty or not geom.is_valid:
                raise ValueError('Invalid relation')
            rows.append({'full_id': f"r{e['id']}", 'name': e.get('tags', {}).get('name', ''), 'geometry': geom})
            relation_members.update(m['ref'] for m in members if m.get('type') == 'way')
        except (ValueError, KeyError, TypeError):
            skipped += 1
    for e in elements:
        if e.get('type') != 'way' or not e.get('tags', {}).get('building') or e['id'] in relation_members:
            continue
        try:
            points = [(p['lon'], p['lat']) for p in e.get('geometry', [])]
            if len(points) < 4 or points[0] != points[-1]:
                raise ValueError('Not closed')
            geom = Polygon(points)
            if geom.is_empty or not geom.is_valid:
                raise ValueError('Invalid polygon')
            rows.append({'full_id': f"w{e['id']}", 'name': e.get('tags', {}).get('name', ''), 'geometry': geom})
        except (ValueError, KeyError, TypeError):
            skipped += 1
    frame = (gpd.GeoDataFrame(rows, crs=4326) if rows else
             gpd.GeoDataFrame({'full_id': [], 'name': [], 'geometry': []}, geometry='geometry', crs=4326))
    return frame, skipped


def fetch_inputs(candidate, radius, directory, requester=request_osm, road_source=None):
    if isinstance(radius, bool) or not math.isfinite(radius) or not 0 < radius <= 1000:
        raise OnlineDataError('在线分析距离需大于0且不超过1000米。')
    roads = roads_frame(candidate['elements'], candidate['name'])
    if roads.to_crs(32650).length.sum() > 20000:
        raise OnlineDataError('所选连通路段超过20公里，请选择更短的候选路段。')
    area = roads.to_crs(32650).geometry.union_all().buffer(radius + 100)
    west, south, east, north = gpd.GeoSeries([area], crs=32650).to_crs(4326).total_bounds
    box_area = (east-west)*111320*math.cos(math.radians((south+north)/2))*(north-south)*111320
    if box_area > 150_000_000:
        raise OnlineDataError('查询区域超过150平方公里，请缩小距离或选择较短路段。')
    bbox = ','.join(f'{v:.7f}' for v in (south, west, north, east))
    query = f'[out:json][timeout:25];(way["building"]({bbox});relation["building"]["type"="multipolygon"]({bbox}););out geom;'
    fetched = requester(query)
    buildings, skipped = buildings_frame(fetched['payload']['elements'])
    if buildings.empty:
        raise OnlineDataError('本次未取得可用建筑轮廓，不能判定周边没有建筑物，也不生成成功分析记录。请尝试其他路段或稍后重试。')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    roads.to_file(directory / 'target_road.geojson', driver='GeoJSON')
    buildings.to_file(directory / 'buildings_osm.geojson', driver='GeoJSON')
    def provenance(item):
        if not item:
            return None
        return {key: item.get(key) for key in ('endpoint', 'retrieved_at', 'query', 'response_sha256')} | {
            'osm_base_timestamp': item['payload'].get('osm3s', {}).get('timestamp_osm_base')}
    return {'provider': 'OpenStreetMap / Overpass API', 'attribution': '© OpenStreetMap contributors',
        'license_url': 'https://www.openstreetmap.org/copyright',
        'road_way_ids': candidate['way_ids'], 'search': provenance(road_source),
        'buildings': provenance(fetched), 'query_bbox_wsen': [west, south, east, north],
        'skipped_invalid_buildings': skipped,
        'coverage': '仅OSM本次查询返回的有效轮廓；非建筑物完整普查。bbox查询可能遗漏无节点落入范围的跨界大面。范围外及占比分母仅针对本次查询样本。'}
