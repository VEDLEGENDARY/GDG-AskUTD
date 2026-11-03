import json
import numpy as np
from pathlib import Path
from semantic_retrieval import ROOT,Models,SemanticRetriever
from lexical_retrieval_v2 import ImprovedRetriever
from hybrid_retrieval import Hybrid,evaluate
from record_classifier import RecordDetector,features
from evaluate_chunks import read_chunks,read_questions
out=ROOT/'runs/hybrid-balanced-scoped';out.mkdir(parents=True,exist_ok=False)
trials=json.loads((ROOT/'runs/hybrid-final/trials.json').read_text());best=max(trials,key=lambda t:(t['minimum'],t['mean']));config=best['config']
models=Models();suites={}
for name,corpus,cache,files in [('students',ROOT/'exports/previous-lokesh',ROOT/'runs/semantic-student/cache',['starter_questions.json','realistic_questions.json','audit_questions.json']),('hard',ROOT.parent/'backend/data/chunks',ROOT/'runs/semantic-hard/cache',['questions.json'])]:
 chunks=read_chunks(corpus);r=Hybrid(SemanticRetriever(chunks,cache,models),ImprovedRetriever(chunks),ROOT/'runs/hybrid-all'/(name+'-cache'))
 for filename in files:suites[filename]=(r,read_questions(ROOT/filename,chunks))
state=(ROOT/'runs/hybrid-final/record-detector.json').read_text();(out/'record-detector.json').write_text(state)
d=RecordDetector.load(models,out/'record-detector.json')
queries=list(dict.fromkeys(q['query'] for _,qs in suites.values() for q in qs));xx=features(queries,models.embed(queries));pp=1/(1+np.exp(-np.clip(xx@d.w,-30,30)));d.probabilities=dict(zip(queries,pp.tolist()))
report=dict(settings=config,selection=best,suites={})
for name,(r,qs) in suites.items():
 r.detector=d
 report['suites'][name]={split:evaluate(r,[q for q in qs if q['split']==split],config,True) for split in ['dev','test'] if any(q['split']==split for q in qs)}
(out/'best-config.json').write_text(json.dumps(config,indent=2))
(out/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({name:{split:v['summary']['leaderboard_score'] for split,v in parts.items()} for name,parts in report['suites'].items()},indent=2))
