"""Local ONNX dense retrieval + cross-encoder reranking. No reference labels in retrieval."""
from pathlib import Path
from functools import lru_cache
from collections import Counter
import argparse, hashlib, json, math, re, unicodedata
import numpy as np
import onnxruntime as ort
from evaluate_chunks import read_chunks, read_questions, grade, summarize, cost, metadata
from lexical_retrieval_v2 import abstention_reason, terms
ROOT=Path(__file__).resolve().parent
HUB=Path.home()/'.cache/huggingface/hub'
EMBED=HUB/'models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
RERANK=HUB/'models--cross-encoder--ms-marco-MiniLM-L6-v2/snapshots/9cc09816f0a7a8aaceefa40a3cfbb843c1bfa579'
class WordPiece:
    """BERT uncased WordPiece using the cached tokenizer's own vocabulary."""
    def __init__(self,path):
        spec=json.loads(path.read_text(encoding='utf-8')); self.vocab=spec['model']['vocab']
        self.maximum=spec['model'].get('max_input_chars_per_word',100)
    @lru_cache(maxsize=50000)
    def encode(self,text):
        clean=[]
        for ch in text:
            cp=ord(ch); category=unicodedata.category(ch)
            if cp in (0,0xfffd) or category in ('Cc','Cf') and ch not in '\t\n\r': continue
            if ch.isspace(): clean.append(' ')
            elif category.startswith('P') or 33<=cp<=47 or 58<=cp<=64 or 91<=cp<=96 or 123<=cp<=126 or 0x4e00<=cp<=0x9fff:
                clean.extend((' ',ch,' '))
            else: clean.append(ch)
        text=''.join(ch for ch in unicodedata.normalize('NFD',''.join(clean).lower()) if unicodedata.category(ch)!='Mn')
        out=[]
        for word in text.split():
            if len(word)>self.maximum: out.append(100);continue
            start=0; pieces=[]
            while start<len(word):
                found=None
                for end in range(len(word),start,-1):
                    token=('##' if start else '')+word[start:end]
                    if token in self.vocab: found=(self.vocab[token],end);break
                if found is None: pieces=[100];break
                pieces.append(found[0]);start=found[1]
            out.extend(pieces)
        return tuple(out)
    def batch(self,pairs,limit):
        encoded=[];types=[]
        for a,b in pairs:
            aa=list(self.encode(a));bb=list(self.encode(b)) if b is not None else None
            if bb is None: row=[101]+aa[:limit-2]+[102];tt=[0]*len(row)
            else:
                aa=aa[:min(96,limit-3)];bb=bb[:max(0,limit-len(aa)-3)]
                row=[101]+aa+[102]+bb+[102];tt=[0]*(len(aa)+2)+[1]*(len(bb)+1)
            encoded.append(row);types.append(tt)
        n=max(map(len,encoded));ids=np.zeros((len(encoded),n),dtype=np.int64);mask=ids.copy();seg=ids.copy()
        for i,(row,tt) in enumerate(zip(encoded,types)):
            ids[i,:len(row)]=row;mask[i,:len(row)]=1;seg[i,:len(row)]=tt
        return dict(input_ids=ids,attention_mask=mask,token_type_ids=seg)
class Models:
    def __init__(self):
        opts=ort.SessionOptions();opts.intra_op_num_threads=3;opts.inter_op_num_threads=1
        self.et=WordPiece(EMBED/'tokenizer.json'); self.rt=WordPiece(RERANK/'tokenizer.json')
        self.e=ort.InferenceSession(str(EMBED/'onnx/model.onnx'),opts,providers=['CPUExecutionProvider'])
        self.r=ort.InferenceSession(str(RERANK/'onnx/model.onnx'),opts,providers=['CPUExecutionProvider'])
    def embed(self,texts):
        result=[]
        for i in range(0,len(texts),24):
            feed=self.et.batch([(t,None) for t in texts[i:i+24]],256)
            output=self.e.run(None,feed)[0]
            if output.ndim==3:
                mask=feed['attention_mask'][:,:,None];output=(output*mask).sum(axis=1)/mask.sum(axis=1)
            output=output/np.maximum(np.linalg.norm(output,axis=1,keepdims=True),1e-12)
            result.extend(output)
        return np.array(result,dtype=np.float32)
    def rerank(self,query,texts):
        scores=[]
        for i in range(0,len(texts),8):
            feed=self.rt.batch([(query,t) for t in texts[i:i+8]],512)
            scores.extend(self.r.run(None,feed)[0].reshape(-1).tolist())
        return scores

def clauses(query):
    parts=[x.strip() for x in re.split(r'[?;]|\band\s+(?=(?:how|who|what|which|where|are|is|does|do|can|the usual)\b)',query,flags=re.I) if x.strip()]
    return [query]+[p for p in parts if p!=query and len(p.split())>=4][:3]
class SemanticRetriever:
    def __init__(self,chunks,cache,models):
        self.chunks=chunks;self.models=models;self.cache=cache;cache.mkdir(parents=True,exist_ok=True)
        self.texts=[metadata(c)+'\n'+c['text'] for c in chunks]
        self.fingerprint=hashlib.sha256(json.dumps(chunks,sort_keys=True).encode()).hexdigest()
        self.years=set(re.findall(r'\b(?:19|20)\d{2}\b',' '.join(self.texts)))
        self.counts=[Counter(terms(t)) for t in self.texts]
        self.df=Counter(t for counts in self.counts for t in counts);self.n=len(chunks)
        target=cache/'embeddings.npz'
        if target.exists():
            stored=np.load(target);assert str(stored['fingerprint'])==self.fingerprint;self.vectors=stored['vectors']
        else:
            self.vectors=models.embed(self.texts);np.savez_compressed(target,vectors=self.vectors,fingerprint=self.fingerprint)
        self.costs=[cost(c) for c in chunks]
    def features(self,query):
        digest=hashlib.sha256(query.encode()).hexdigest(); path=self.cache/(digest+'.json')
        if path.exists():return json.loads(path.read_text())
        reason=abstention_reason(query,self.years)
        result=dict(query=query,reason=reason,candidates=[])
        if not reason:
            parts=clauses(query); vv=self.models.embed(parts); ds=vv@self.vectors.T
            candidates=set()
            for row in ds:candidates.update(np.argsort(-row)[:12].tolist())
            ts=set(terms(query))
            lexical=np.array([sum(math.log(1+(self.n-self.df[t]+.5)/(self.df[t]+.5))*min(2,c[t]) for t in ts if c[t]) for c in self.counts])
            candidates.update(np.argsort(-lexical)[:12].tolist())
            indices=sorted(candidates); scores=self.models.rerank(query,[self.texts[i] for i in indices])
            for i,score in zip(indices,scores):
                result['candidates'].append(dict(index=i,score=score,dense=float(ds[:,i].max()),lexical=float(lexical[i]/max(1,float(lexical.max()))),cost=self.costs[i]))
        path.write_text(json.dumps(result),encoding='utf-8');return result
    def retrieve(self,query,s):
        data=self.features(query)
        if data['reason']:return [],data['reason']
        ranked=[]
        for row in data['candidates']:
            value=row['score']+s['dense_weight']*row['dense']+s['lexical_weight']*row['lexical']-s['length_penalty']*math.log1p(row['cost']/100)
            ranked.append((value,row))
        ranked.sort(key=lambda x:(-x[0],x[1]['index']))
        hits=[];used=0;counts=Counter()
        for value,row in ranked:
            if len(hits)>=s['top_k']:break
            if value<s['min_score'] or value<ranked[0][0]-s['score_gap']:continue
            c=self.chunks[row['index']]
            if counts[c['doc_id']]>=s['max_per_document'] or used+row['cost']>900:continue
            hits.append({**c,'estimated_tokens':row['cost'],'retrieval_score':value});used+=row['cost'];counts[c['doc_id']]+=1
        return hits,None
DEFAULT=dict(dense_weight=1.,lexical_weight=.5,length_penalty=.1,top_k=3,min_score=0.,score_gap=4.,max_per_document=3)
def evaluate(r,questions,s,full=False):
    rows=[]
    for q in questions:
        hits,reason=r.retrieve(q['query'],s);row=dict(metrics=grade(q,hits))
        if full:row.update(question=q,retrieved=hits,abstention_reason=reason)
        rows.append(row)
    result=dict(summary=summarize(rows))
    result['by_category']={category:summarize([row for row,q in zip(rows,questions) if q['category']==category]) for category in sorted({q['category'] for q in questions})}
    if full:result['results']=rows
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--chunks',type=Path,default=ROOT.parent/'backend/data/chunks');p.add_argument('--questions',type=Path,nargs='+',default=[ROOT/'questions.json']);p.add_argument('--output',type=Path,required=True);p.add_argument('--config',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);chunks=read_chunks(a.chunks);models=Models();r=SemanticRetriever(chunks,a.output/'cache',models)
    suites={path.stem:read_questions(path,chunks) for path in a.questions}
    total=sum(len(qs) for qs in suites.values());done=0
    for name,questions in suites.items():
        for q in questions:
            r.features(q['query']);done+=1
            if done%5==0:print(f'Prepared {done}/{total} questions',flush=True)
    # Only dev scores select settings. No labels enter feature preparation.
    dev=[q for qs in suites.values() for q in qs if q['split']=='dev']
    settings=json.loads(a.config.read_text()) if a.config else DEFAULT
    if dev and not a.config:
        trials=[]
        for top_k in [1,2,3,4,5]:
            for gap in [1.,2.,3.,4.,6.,8.]:
                for threshold in [-3.,-1.,0.,2.,4.]:
                    s={**DEFAULT,'top_k':top_k,'score_gap':gap,'min_score':threshold}
                    # Macro-average across suites so easy sets cannot dominate.
                    summaries=[evaluate(r,[q for q in qs if q['split']=='dev'],s)['summary'] for qs in suites.values() if any(q['split']=='dev' for q in qs)]
                    scores=[m['leaderboard_score'] for m in summaries if m['leaderboard_score'] is not None]
                    trials.append(dict(settings=s,score=sum(scores)/len(scores),minimum=min(scores)))
        best=max(trials,key=lambda t:(t['minimum'],t['score'],-t['settings']['top_k']));settings=best['settings']
        (a.output/'trials.json').write_text(json.dumps(trials,indent=2))
    (a.output/'best-config.json').write_text(json.dumps(settings,indent=2))
    report=dict(settings=settings,corpus_sha256=r.fingerprint,models=dict(embedding=str(EMBED),reranker=str(RERANK)),suites={})
    for name,questions in suites.items():
        report['suites'][name]={split:evaluate(r,[q for q in questions if q['split']==split],settings,True) for split in ['dev','test'] if any(q['split']==split for q in questions)}
    (a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:{split:obj['summary'] for split,obj in parts.items()} for name,parts in report['suites'].items()},indent=2),flush=True)
if __name__=='__main__':main()
