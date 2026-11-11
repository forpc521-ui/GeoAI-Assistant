"""Small paired local/model task parsing check, without modifying data/history."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,os
from gis_local import active_dataset
from gis_local_parser import parse_local_query

CASES=[
 {'id':'P01','query':'分析交大东路周边500米范围内的建筑物','expected':['交大东路',500]},
 {'id':'P02','query':'分析学院路周边0.5公里范围内的建筑物','expected':['学院路',500]},
 {'id':'P03','query':'帮我看看中关村大街附近300米有哪些建筑物','expected':['中关村大街',300]},
 {'id':'P04','query':'交大东路两边1公里内有多少建筑物？','expected':['交大东路',1000]},
 {'id':'P05','query':'请查询颐和园路周围250米以内的建筑物','expected':['颐和园路',250]},
 {'id':'P06','query':'帮我统计中关村南大街附近半公里的建筑物','expected':['中关村南大街',500]},
 {'id':'P07','query':'分析交大东路周边500米建筑物，计算平均高度','expected':None},
 {'id':'P08','query':'分析交大东路周边500米建筑物并预测未来人口','expected':None},
 {'id':'P09','query':'分析交大东路周边500米和1000米的建筑物','expected':None},
 {'id':'P10','query':'分析完全不存在的测试路周边500米建筑物','expected':None}
]


if __name__=='__main__':
    out=Path(os.environ['GEOAI_EVAL_OUTPUT'])
    out.mkdir(exist_ok=True)
    (out/'parsing_cases.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding='utf-8')
    directory,_=active_dataset();names=json.loads((directory/'road_names.json').read_text(encoding='utf-8'))
    def one(pair):
        case,mode=pair;result=dict(case,mode=mode)
        try:
            task=parse_local_query(case['query'],names,mode)
            result['actual']=[task.road_name,task.distance_m]
            result['correct']=result['actual']==case['expected']
        except ValueError as e:
            result['message']=str(e)
            # API/configuration errors are failures, never a correct refusal.
            network=str(e).startswith('DeepSeek')
            result['correct']=case['expected'] is None and not network
        return result
    pairs=[(case,mode) for mode in ['本地规则（无需API）','DeepSeek（API指令解析）'] for case in CASES]
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,pairs))
    (out/'parsing_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for mode in ['本地规则（无需API）','DeepSeek（API指令解析）']:
        subset=[r for r in results if r['mode']==mode]
        print(json.dumps({'mode':mode,'correct':sum(r['correct'] for r in subset),'total':len(subset),
            'valid_correct':sum(r['correct'] for r in subset if r['expected']),'valid_total':6,
            'invalid_correct':sum(r['correct'] for r in subset if r['expected'] is None),'invalid_total':4},ensure_ascii=True))
