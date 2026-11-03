"""Clause-aware lexical/semantic hybrid. Fits settings on dev, reports all suites."""
from pathlib import Path
from collections import Counter
import hashlib,json,math,re,time
import numpy as np
from semantic_retrieval import Models,SemanticRetriever,ROOT
from lexical_retrieval_v2 import ImprovedRetriever,abstention_reason
from evaluate_chunks import read_chunks,read_questions,grade,summarize,cost

def record_reason(query,years):
    reason=abstention_reason(query,years)
    if reason:return reason
    q=query.lower()
    patterns=[r'\bmy\s+(?:orion\s+)?enrollment appointment\b',
     r'\bhow many\b.*\b(?:my own|have i|i have)\b.*\b(?:used|completed|received)\b',
     r'\b(?:has|did|was|have)\b.*\bmy\b.*\b(?:approved|accepted|processed|granted)\b',
     r'\bwhich\b.*\b(?:currently|already)\b.*\bmy\b.*\b(?:permission|consent|record)\b',
     r'\bmy\b.*\b(?:corrected|current|actual)\b.*\b(?:gpa|balance|grade|appointment)\b',
     r'\b(?:is|has)\b.*\bcourse i am taking\b.*\b(?:excluded|approved|eligible)\b']
    if any(re.search(p,q) for p in patterns):return 'Requires individual records or an identified course; public policies cannot establish the requested status'
    return None
class Hybrid:
    def __init__(self,semantic,lexical,store):self.s=semantic;self.l=lexical;self.store=store;self.store.mkdir(parents=True,exist_ok=True);self.prepared={}
    def prepare(self,q):
        if q in self.prepared:return self.prepared[q]
        reason=record_reason(q,self.s.years)
        if reason:value=dict(reason=reason);self.prepared[q]=value;return value
        raw=self.s.features(q);_,arrays=self.l.prepare(q)
        lex=np.array([.2*bm+.1*meta+.7*cov for bm,meta,cov,_ in arrays])
        allowed=np.array([a[-1] for a in arrays]);lex=np.where(allowed,lex,0)
        candidates={row['index']:row['score'] for row in raw['candidates']}
        for row in lex:
            for index in np.argsort(-row)[:8]:candidates.setdefault(int(index),None)
        path=self.store/(hashlib.sha256(q.encode()).hexdigest()+'.json')
        if path.exists():candidates.update({int(k):v for k,v in json.loads(path.read_text()).items()})
        if any(v is None for v in candidates.values()):
            missing=[i for i,v in candidates.items() if v is None]
            if missing:
                scores=self.s.models.rerank(q,[self.s.texts[i] for i in missing])
                candidates.update(zip(missing,scores))
            path.write_text(json.dumps(candidates))
        indices=list(candidates);ce=np.array([1/(1+math.exp(-max(-50,min(50,candidates[i]/3)))) for i in indices])
        value=dict(reason=None,indices=indices,ce=ce,lex=lex[:,indices]);self.prepared[q]=value;return value
    def retrieve(self,q,config):
        data=self.prepare(q)
        if data['reason']:return [],data['reason']
        if getattr(self,'detector',None):
            reason=self.detector.reason(q)
            if reason:return [],reason
        indices=data['indices'];w=config['semantic_weight'];scores=w*data['ce'][None,:]+(1-w)*data['lex']
        # Start with whole-question ranking, then find complementary clause evidence.
        ordered=[scores.max(axis=0)]+list(scores)
        selected=[];used=0;docs=Counter()
        for row in ordered:
            if len(selected)>=config['top_k']:break
            best=float(row.max())
            if selected and any(row[j]>=best*config['coverage_ratio'] for j in selected):continue
            feasible=[j for j in np.argsort(-row) if row[j]>=config['min_score'] and row[j]>=best-config['gap'] and j not in selected and docs[self.s.chunks[indices[j]]['doc_id']]<3 and used+self.s.costs[indices[j]]<=900]
            if feasible:
                j=int(feasible[0]);selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1
        # Optional one extra passage helps facts spread over adjacent chunks.
        for _ in range(int(config['extra'])):
            if len(selected)>=config['top_k']:break
            row=scores.max(axis=0);best=float(row.max())
            feasible=[j for j in np.argsort(-row) if j not in selected and row[j]>=config['min_score'] and row[j]>=best-config['gap'] and used+self.s.costs[indices[j]]<=900 and docs[self.s.chunks[indices[j]]['doc_id']]<3]
            if feasible:
                j=int(feasible[0]);selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1
        return [{**self.s.chunks[indices[j]],'estimated_tokens':self.s.costs[indices[j]]} for j in selected],None

def evaluate(r,questions,c,full=False):
    rows=[]
    for q in questions:
        hits,reason=r.retrieve(q['query'],c);row=dict(metrics=grade(q,hits))
        if full:row.update(question=q,retrieved=hits,abstention_reason=reason)
        rows.append(row)
    return dict(summary=summarize(rows),**(dict(results=rows) if full else {}))

def main():
    out=ROOT/'runs/hybrid-final';out.mkdir(parents=True,exist_ok=False);models=Models();suites={}
    specs=[('students',ROOT/'exports/previous-lokesh',ROOT/'runs/semantic-student/cache',['starter_questions.json','realistic_questions.json','audit_questions.json']),('hard',ROOT.parent/'backend/data/chunks',ROOT/'runs/semantic-hard/cache',['questions.json'])]
    for name,corpus,cache,files in specs:
        chunks=read_chunks(corpus);semantic=SemanticRetriever(chunks,cache,models);r=Hybrid(semantic,ImprovedRetriever(chunks),ROOT/'runs/hybrid-all'/(name+'-cache'))
        for filename in files:
            qs=read_questions(ROOT/filename,chunks);suites[filename]=(r,qs)
            for q in qs:r.prepare(q['query'])
            print('Prepared hybrid '+filename,flush=True)
    from record_classifier import RecordDetector
    detector=RecordDetector(models,suites,out/'record-detector.json')
    for r,_ in suites.values():r.detector=detector
    trials=[]
    for weight in [0.,.25,.5,.75,1.]:
      for gap in [.05,.15,.3]:
       for floor in [.15,.3,.45]:
        for extra in [0,1,2,3]:
         c=dict(semantic_weight=weight,gap=gap,min_score=floor,extra=extra,top_k=5,coverage_ratio=.95)
         dev=[evaluate(r,[q for q in qs if q['split']=='dev'],c)['summary']['leaderboard_score'] for r,qs in suites.values() if any(q['split']=='dev' for q in qs)]
         trials.append(dict(config=c,minimum=min(dev),mean=sum(dev)/len(dev),dev_scores=dev))
    eligible=[t for t in trials if min(t['dev_scores'][:2])>=90]
    best=max(eligible or trials,key=lambda t:(t['minimum'],t['mean']));config=best['config']
    (out/'best-config.json').write_text(json.dumps(config,indent=2));(out/'trials.json').write_text(json.dumps(trials,indent=2))
    report=dict(settings=config,selection=best,suites={})
    for name,(r,qs) in suites.items():
        report['suites'][name]={split:evaluate(r,[q for q in qs if q['split']==split],config,True) for split in ['dev','test'] if any(q['split']==split for q in qs)}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:{split:v['summary'] for split,v in parts.items()} for name,parts in report['suites'].items()},indent=2),flush=True)
if __name__=='__main__':main()
