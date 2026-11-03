"""Evaluate frozen hard retriever and passage-support model on one split."""
import argparse,json,hashlib
from pathlib import Path
from hard_retrieval import *
from passage_support import matrix,predict

def run(r,qs,state):
 rows=[]
 for count,q in enumerate(qs):
  hits,reason=r.retrieve(q['query'],state['base_settings'])
  if hits:
   v=r.prepare(q['query']);probs=predict(matrix(r,v),state);lookup={r.s.chunks[i]['chunk_id']:float(p) for i,p in zip(v['indices'],probs)}
   original=hits;hits=[{**h,'support_probability':lookup[h['chunk_id']]} for h in hits if lookup[h['chunk_id']]>=state['threshold']]
   if not hits:
    h=max(original,key=lambda h:lookup[h['chunk_id']]);hits=[{**h,'support_probability':lookup[h['chunk_id']]}]
   if state.get('rerank'):hits.sort(key=lambda h:-h['support_probability'])
  rows.append(dict(question=q,metrics=grade(q,hits),retrieved=hits,abstention_reason=reason))
  print(f'Evaluated {count+1}/{len(qs)}: {q["id"]}',flush=True)
 return dict(summary=summarize(rows),results=rows)
def main():
 p=argparse.ArgumentParser();p.add_argument('--split',choices=['dev','test'],default='test');p.add_argument('--model',type=Path,default=ROOT/'runs/hard-support-dev/support-model.json');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise ValueError('Choose a new report file')
 state=json.loads(a.model.read_text());chunks=read_chunks(ROOT.parent/'backend/data/chunks');qs=read_questions(ROOT/'questions.json',chunks,split=a.split)
 s=SemanticRetriever(chunks,ROOT/'runs/semantic-hard/cache',FastModels());r=FacetRetriever(s,ROOT/'runs/hard-facets-cache-v2')
 report=run(r,qs,state);report.update(split=a.split,corpus_sha256=s.fingerprint,questions_sha256=hashlib.sha256(json.dumps(qs,sort_keys=True).encode()).hexdigest(),settings=state['base_settings'],support_model_sha256=hashlib.sha256(a.model.read_bytes()).hexdigest())
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report['summary'],indent=2),flush=True)
if __name__=='__main__':main()
