"""Frozen exploratory RAG quality evaluation using the actual app functions.

Gold IDs index the frozen vector metadata, not file names. No index rebuilding.
"""
import ast
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,json,os,time
from pathlib import Path
import faiss
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('GEOAI_EVAL_OUTPUT',str(ROOT/'05_Demo'/'ai_quality_20261111')))


def run():
    OUT.mkdir(parents=True,exist_ok=False)
    load_dotenv(ROOT/'.env')
    source=ROOT/'04_Code/app.py';vector=ROOT/'03_Data/vector_database'
    cases_path=ROOT/'03_Data/evaluation/rag_cases_v1.json'
    cases=json.loads(cases_path.read_text(encoding='utf-8'))
    docs=json.loads((vector/'metadata.json').read_text(encoding='utf-8'))
    provenance={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,cases_path,vector/'metadata.json',vector/'gis.index']}
    (OUT/'provenance.json').write_text(json.dumps({'sha256':provenance,'k':3,'temperature':0.2,'max_tokens':1200,'transport_timeout':35,'max_retries':0,'concurrency':2,'gold_scope':'independently sufficient answer-bearing chunks; empty gold excluded from retrieval denominator; hand-labeled developer set, not independent test data'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'frozen_metadata.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2),encoding='utf-8')
    responses=[]
    def client(**kwargs):
        real=OpenAI(**kwargs,timeout=35,max_retries=0)
        original=real.chat.completions.create
        def wrapped(**params):
            r=original(**params)
            responses.append({'id':r.id,'model':r.model,'usage':r.usage.model_dump() if r.usage else None})
            return r
        real.chat.completions.create=wrapped
        return real
    namespace={'VECTOR_DIR':vector,'faiss':faiss,'json':json,'np':np,'API_KEY':os.getenv('DEEPSEEK_API_KEY'),'OpenAI':client,
               'SentenceTransformer':lambda name:SentenceTransformer(name,local_files_only=True)}
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ['load_knowledge_base','search_knowledge','generate_answer']]
    for node in functions:node.decorator_list=[]
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec'),namespace)
    index,metadata,model=namespace['load_knowledge_base']()
    results=[]
    for case in cases:
        hits=namespace['search_knowledge'](case['question'],index,metadata,model)
        ids=[next(i for i,d in enumerate(docs) if d['source']==h['source'] and d['content']==h['content']) for h in hits]
        gold=set(case['gold']);tp=len(gold.intersection(ids))
        results.append(dict(case,retrieved_ids=ids,hits=hits,recall=tp/len(gold) if gold else None,precision=tp/len(ids) if gold and ids else (0 if gold else None)))
    (OUT/'retrieval.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Retrieval complete; starting real model answers',flush=True)
    def answer(item):
        start=time.monotonic()
        try:item['answer']=namespace['generate_answer'](item['question'],item['hits']);item['status']='ok'
        except Exception as exc:item['status']='api_error';item['error_type']=type(exc).__name__
        item['elapsed_seconds']=time.monotonic()-start
        return item
    completed=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(answer,item) for item in results]):
            item=future.result();completed.append(item)
            (OUT/'answers.json').write_text(json.dumps(sorted(completed,key=lambda x:x['id']),ensure_ascii=False,indent=2),encoding='utf-8')
            print(item['id'],item['status'],round(item['elapsed_seconds'],2),flush=True)
    (OUT/'api_usage.json').write_text(json.dumps(responses,ensure_ascii=False,indent=2),encoding='utf-8')
    valid=[r for r in results if r['gold']]
    metrics={'answerable_cases':len(valid),'unanswerable_cases':len(results)-len(valid),'recall_at_3_macro':sum(r['recall'] for r in valid)/len(valid),'precision_at_3_macro':sum(r['precision'] for r in valid)/len(valid),'generation_success':sum(r['status']=='ok' for r in results),'generation_attempts':len(results),'hallucination_rate':None,'note':'Hallucination rate requires evidence-based assessment of saved answers; not scored from API success.'}
    (OUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metrics),flush=True)


if __name__=='__main__':run()
