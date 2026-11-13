import json
import numpy as np
from hard_retrieval import *
from passage_support import matrix,fit,predict
from evaluate_chunks import supports
out=ROOT/'runs/hard-support-dev';out.mkdir(parents=True,exist_ok=False)
chunks=read_chunks(ROOT.parent/'backend/data/chunks');qs=read_questions(ROOT/'questions.json',chunks,split='dev')
r=FacetRetriever(SemanticRetriever(chunks,ROOT/'runs/semantic-hard/cache',FastModels()),ROOT/'runs/hard-facets-cache-v2')
xs=[];ys=[];groups=[];matrices={}
for qi,q in enumerate(qs):
 v=r.prepare(q['query'])
 if v['reason']:continue
 x=matrix(r,v);y=np.array([any(supports(chunks[i],e) for e in q['evidence']) for i in v['indices']],dtype=float)
 xs.append(x);ys.append(y);groups.extend([qi]*len(y));matrices[q['query']]=x
x=np.vstack(xs);y=np.concatenate(ys);groups=np.array(groups)
base=json.loads((ROOT/'runs/hard-refined-dev/best-config.json').read_text())
# Source selection stays fixed while passage-filter calibration uses held-out question folds.
trials=[];predictions={}
for reg in [.01,.1,1.]:
 oof=np.zeros(len(y))
 for fold in range(5):
  train=groups%5!=fold;state=fit(x[train],y[train],reg);oof[~train]=predict(x[~train],state)
 offset=0;probs={}
 for q in qs:
  if q['query'] not in matrices:continue
  n=len(matrices[q['query']]);probs[q['query']]=oof[offset:offset+n];offset+=n
 for threshold in [.25,.4,.55,.7,.85]:
  for rerank in [False,True]:
   results=[]
   for q in qs:
    hits,reason=r.retrieve(q['query'],base)
    if hits:
     v=r.prepare(q['query']);pp=probs[q['query']];lookup={chunks[i]['chunk_id']:float(p) for i,p in zip(v['indices'],pp)}
     original=hits;hits=[h for h in hits if lookup[h['chunk_id']]>=threshold]
     if not hits:hits=[max(original,key=lambda h:lookup[h['chunk_id']])]
     if rerank:hits.sort(key=lambda h:-lookup[h['chunk_id']])
    results.append(dict(metrics=grade(q,hits)))
   trials.append(dict(reg=reg,threshold=threshold,rerank=rerank,summary=summarize(results)))
 best_reg=max([t for t in trials if t['reg']==reg],key=lambda t:t['summary']['leaderboard_score']);print('OOF',reg,best_reg,flush=True)
best=max(trials,key=lambda t:t['summary']['leaderboard_score']);state=fit(x,y,best['reg']);state.update(threshold=best['threshold'],rerank=best['rerank'],calibration=best,base_settings=base)
(out/'support-model.json').write_text(json.dumps(state,indent=2));(out/'trials.json').write_text(json.dumps(trials,indent=2));print('SELECTED',best,flush=True)
