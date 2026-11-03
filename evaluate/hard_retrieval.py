"""Hard-benchmark retrieval: question facets, edition routing, local context.
Reference evidence is used only by evaluation, never candidate preparation/selection.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,hashlib,json,math,re,time
import numpy as np
from semantic_retrieval import ROOT,Models,SemanticRetriever
from lexical_retrieval_v2 import terms,ImprovedRetriever
from hybrid_retrieval import record_reason
from evaluate_chunks import read_chunks,read_questions,metadata,cost,grade,summarize

class FastModels(Models):
    def rerank(self,query,texts):
        # Bucket similar lengths to avoid padding every short fragment to 512.
        order=sorted(range(len(texts)),key=lambda i:len(self.rt.encode(texts[i])))
        result=[0.]*len(texts)
        for start in range(0,len(order),8):
            ids=order[start:start+8]
            feed=self.rt.batch([(query,texts[i]) for i in ids],512)
            scores=self.r.run(None,feed)[0].reshape(-1)
            for i,value in zip(ids,scores):result[i]=float(value)
        return result

PROGRAMS={'computer science':('computer science',r'\bcs\b'),'software engineering':('software engineering',r'\bse\b'),'computer engineering':('computer engineering',r'\bce\b')}
ALIASES={'temporary grade':'incomplete grade','three quarters':'75 percent','another bachelors':'second baccalaureate','semester honors':'deans list','school level semester honors':'deans list','multivariable calculus':'calculus of several variables','computer architecture prefix':'computer architecture course number','course removal':'dropping class','stop attending':'nonattendance','without paying':'non payment','filing period':'filing deadline','normal completion limit':'completion deadline','responsible university official':'responsible university official RUO'}

def rewrite(q):
    for a,b in sorted(ALIASES.items(),key=lambda x:-len(x[0])):q=re.sub(r'\b'+re.escape(a)+r'\b',b,q,flags=re.I)
    return q

def requests(q):
    # Named program conjunctions are expanded independently below.
    parts=re.split(r'[?;]|,\s*(?=(?:what|how|which|who|where|whether|why)\b)|\band\s+(?=(?:what|how|which|who|where|whether|why|identify|give|explain|the normal|the usual|the rule)\b)',q,flags=re.I)
    parts=[p.strip(' .,:') for p in parts if len(p.split())>=3]
    context=q.split('.')[0] if '.' in q else ''
    result=[]
    for part in parts:
        if context and part!=context and len(part.split())<14:part=part+' '+context
        result.append(rewrite(part))
    return list(dict.fromkeys([rewrite(q)]+result))[:6]

def program_names(text):
    result=[];text=text.lower()
    for name,(full,abbr) in PROGRAMS.items():
        if full in text or re.search(abbr,text):result.append(name)
    return result

def reject_reason(q,sem):
    reason=record_reason(q,sem.years)
    if reason:return reason
    lower=q.lower();own=bool(re.search(r'\b(my|mine|me|i|our)\b',lower))
    if own and re.search(r'\b(?:what did|what was|what has|did|has|have)\b',lower) and re.search(r'\b(?:decide|decided|decision|approved|accepted|granted|processed)\b',lower) and not re.search(r'\b(?:if|policy|procedure|rule|appeal deadline)\b',lower):
        return 'An individual decision requires the student record, not a public policy'
    if own and re.search(r'\b(?:exact|exactly|how many dollars)\b',lower) and re.search(r'\b(?:dollars|amount|repay|repayment|refund|financial aid)\b',lower):
        return 'Exact personal financial consequences require account and aid records'
    if re.search(r'\b(?:unspecified|unnamed|unidentified)\b',lower) and re.search(r'\b(?:course|credit|transcript|record)\b',lower):
        return 'The course or record must be identified before applicability can be established'
    years=set(re.findall(r'\b(?:19|20)\d{2}\b',q))
    ranges=re.findall(r'\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b',q)
    editions=[set(pair) for pair in ranges] or [years]
    if years and re.search(r'\b(?:plan|catalog)\b',lower):
        wanted=program_names(re.sub(r'\bdo not\b[^.?!]*','',lower))
        titles=[metadata(c) for c in sem.chunks if not wanted or any(p in metadata(c).lower() for p in wanted)]
        if any(not any(edition.issubset(set(re.findall(r'\b(?:19|20)\d{2}\b',title))) for title in titles) for edition in editions):
            return 'Requested catalog/plan edition is not represented in the source metadata'
    return None

class FacetRetriever:
    def __init__(self,sem,cache):
        self.s=sem;self.cache=cache;cache.mkdir(parents=True,exist_ok=True);self.data={}
        self.lex=ImprovedRetriever(sem.chunks);self.doc_indices=defaultdict(list)
        for i,c in enumerate(sem.chunks):self.doc_indices[c['doc_id']].append(i)
        def number(i):
            m=re.search(r'_c(\d+)$',sem.chunks[i]['chunk_id']);return int(m.group(1)) if m else i
        for rows in self.doc_indices.values():rows.sort(key=number)
        self.where={i:(doc,position) for doc,rows in self.doc_indices.items() for position,i in enumerate(rows)}
        self.doc_titles={doc:' '.join(dict.fromkeys(sem.chunks[i]['source_title'] for i in rows)) for doc,rows in self.doc_indices.items()}
    def route(self,q):
        positive=re.sub(r'\bdo not\b[^.?!]*','',q,flags=re.I)
        programs=program_names(positive);years=set(re.findall(r'\b(?:19|20)\d{2}\b',positive))
        ranges=re.findall(r'\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b',positive)
        editions=[set(pair) for pair in ranges] or [years]
        codes=re.findall(r'\bUTD(?:SP|PP|BP)\d+\b',q,re.I)
        routed=[]
        if programs and years and re.search(r'\bplan|catalog\b',q,re.I):
            for program in programs:
                matches=[doc for doc,title in self.doc_titles.items() if program in title.lower() and any(edition.issubset(set(re.findall(r'\b(?:19|20)\d{2}\b',title))) for edition in editions)]
                # Prefer a degree-plan source to an eight-semester map when available.
                plans=[doc for doc in matches if re.search(r'degree plan|b\.s\.|b s in',self.doc_titles[doc],re.I) and not re.search(r'map|four.year|eight.semester',self.doc_titles[doc],re.I)]
                routed.extend(plans or matches)
        for code in codes:routed.extend(doc for doc,title in self.doc_titles.items() if code.lower() in title.lower())
        return list(dict.fromkeys(routed))
    def prepare(self,q):
        if q in self.data:return self.data[q]
        path=self.cache/(hashlib.sha256(q.encode()).hexdigest()+'.json')
        if path.exists():
            value=json.loads(path.read_text())
            if value['reason']==reject_reason(q,self.s):self.data[q]=value;return value
        reason=reject_reason(q,self.s)
        if reason:value=dict(query=q,reason=reason);path.write_text(json.dumps(value));self.data[q]=value;return value
        facets=requests(q);routed=self.route(q)
        # Scope each program comparison separately and ask for distinct requested fields.
        if routed:
            scoped=[]
            for doc in routed:
                title=self.doc_titles[doc]
                aspects=[]
                for part in facets[1:] or facets:aspects.append(part)
                if re.search(r'total hours',q,re.I):aspects.append('What are the total required degree hours?')
                if re.search(r'computer architecture',q,re.I):aspects.append('What is the computer architecture course number and prefix?')
                if re.search(r'technical.?elective.*hours',q,re.I):aspects.append('How many technical elective hours are required?')
                if re.search(r'free.?elective.*hours',q,re.I):aspects.append('How many free elective hours are required?')
                for aspect in aspects:
                    aspect=re.sub(r'\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b','',aspect)
                    scoped.append((rewrite(aspect)+' '+title,doc))
        else:scoped=[(f,None) for f in facets]
        # One full-query query remains available, with all smaller facets.
        scoped=[(rewrite(q),None)]+scoped
        scoped=list(dict.fromkeys(scoped))[:12]
        facet_texts=[text for text,doc in scoped]
        dense=self.s.models.embed(facet_texts)@self.s.vectors.T
        candidate=set();lexical=[];route_boost=[]
        for f,(text,doc) in enumerate(scoped):
            _,arrays=self.lex.prepare(text)
            lex=np.max(np.array([.45*bm+.15*meta+.4*coverage for bm,meta,coverage,allowed in arrays]),axis=0)
            if doc:
                mask=np.zeros(len(self.s.chunks),dtype=bool);mask[self.doc_indices[doc]]=True
                lex=np.where(mask,lex,0);scores=np.where(mask,dense[f],-np.inf)
                candidate.update(self.doc_indices[doc])
            else:scores=dense[f]
            candidate.update(np.argsort(-scores)[:8].tolist());candidate.update(np.argsort(-lex)[:8].tolist());lexical.append(lex)
        # Local continuity restores short adjacent exceptions/deadlines.
        seeds=list(candidate)
        for i in seeds:
            doc,pos=self.where[i];rows=self.doc_indices[doc]
            for offset in [-1,1]:
                j=pos+offset
                if 0<=j<len(rows):candidate.add(rows[j])
        indices=sorted(candidate)
        # Restrict a degree-plan-only comparison to the requested editions/programs.
        if routed and re.search(r'\bplan',q,re.I) and not re.findall(r'\bUTD(?:SP|PP|BP)\d+\b',q,re.I):
            indices=[i for i in indices if self.s.chunks[i]['doc_id'] in routed]
        ce=[]
        for f,(text,doc) in enumerate(scoped):
            if doc:
                chosen=[j for j,i in enumerate(indices) if self.s.chunks[i]['doc_id']==doc]
            else:
                preliminary=.6*dense[f,indices]+.4*np.array(lexical)[f,indices]
                chosen=np.argsort(-preliminary)[:20].tolist()
            values=[-12.]*len(indices)
            reranked=self.s.models.rerank(text,[self.s.texts[indices[j]] for j in chosen])
            for j,value in zip(chosen,reranked):values[j]=value
            ce.append(values)
        value=dict(query=q,reason=None,facets=scoped,indices=indices,ce=ce,
                   lexical=np.array(lexical)[:,indices].tolist(),dense=dense[:,indices].tolist(),routed=routed)
        path.write_text(json.dumps(value));self.data[q]=value;return value
    def retrieve(self,q,c):
        v=self.prepare(q)
        if v['reason']:return [],v['reason']
        indices=v['indices'];ce=1/(1+np.exp(-np.clip(np.array(v['ce'])/3,-30,30)))
        lex=np.array(v['lexical']);ds=np.maximum(0,np.array(v['dense']))
        score=c['semantic_weight']*ce+(1-c['semantic_weight'])*(.8*lex+.2*ds)
        for row,(_,doc) in enumerate(v['facets']):
            if doc:score[row,[j for j,i in enumerate(indices) if self.s.chunks[i]['doc_id']!=doc]]=-np.inf
        selected=[];used=0;docs=Counter()
        order=list(range(1,len(score)))+[0]
        # Each intent gets a chance before generic whole-question matches.
        for f in order:
            if len(selected)>=c['top_k']:break
            row=score[f];best=float(row.max())
            if selected and any(row[j]>=best*c['covered_ratio'] for j in selected):continue
            choices=[int(j) for j in np.argsort(-row) if j not in selected and row[j]>=c['min_score'] and row[j]>=best-c['gap'] and used+self.s.costs[indices[j]]<=900 and docs[self.s.chunks[indices[j]]['doc_id']]<c['per_doc']]
            if choices:
                j=choices[0];selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1
        for _ in range(c['extra']):
            if len(selected)>=c['top_k']:break
            row=score.max(axis=0);best=float(row.max())
            choices=[int(j) for j in np.argsort(-row) if j not in selected and row[j]>=c['min_score'] and row[j]>=best-c['gap'] and used+self.s.costs[indices[j]]<=900 and docs[self.s.chunks[indices[j]]['doc_id']]<c['per_doc']]
            if not choices:break
            def adjacent(j):
                doc,pos=self.where[indices[j]]
                return any(self.where[indices[k]][0]==doc and abs(self.where[indices[k]][1]-pos)==1 for k in selected)
            j=max(choices,key=lambda j:(row[j]+c.get('neighbor_boost',0)*adjacent(j),-j));selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1
        if c.get('prune_ratio',0):
            for j in sorted(list(selected),key=lambda j:float(score[:,j].max())):
                remaining=[k for k in selected if k!=j]
                if not remaining:break
                before=score[:,selected].max(axis=1);after=score[:,remaining].max(axis=1)
                valid=np.isfinite(before)
                if np.all(after[valid]>=before[valid]*c['prune_ratio']):selected.remove(j)
        return [{**self.s.chunks[indices[j]],'estimated_tokens':self.s.costs[indices[j]]} for j in selected],None

def evaluate(r,qs,c,full=False):
    rows=[]
    for q in qs:
        hits,reason=r.retrieve(q['query'],c);row=dict(metrics=grade(q,hits))
        if full:row.update(question=q,retrieved=hits,abstention_reason=reason)
        rows.append(row)
    return dict(summary=summarize(rows),**(dict(results=rows) if full else {}))

def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['dev','test'],default='dev');p.add_argument('--config',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);chunks=read_chunks(ROOT.parent/'backend/data/chunks')
    qs=read_questions(ROOT/'questions.json',chunks,split=a.split)
    models=FastModels();s=SemanticRetriever(chunks,ROOT/'runs/semantic-hard/cache',models);r=FacetRetriever(s,ROOT/'runs/hard-facets-cache-v2')
    for i,q in enumerate(qs):r.prepare(q['query']);print(f'Prepared {a.split} {i+1}/{len(qs)}: {q["id"]}',flush=True)
    if a.config:config=json.loads(a.config.read_text())
    else:
        if a.split!='dev':raise ValueError('Test requires a frozen dev config')
        seeds=json.loads((ROOT/'runs/hard-facets-dev-v3/trials.json').read_text())
        seeds=sorted(seeds,key=lambda t:-t['summary']['leaderboard_score'])[:12]
        trials=[]
        seen=set()
        for seed in seeds:
         for neighbor in [0.,.1,.25,.5]:
          for prune in [0.,.9,.97,.995]:
           for top in [4,5,6,7]:
            c={**seed['settings'],'neighbor_boost':neighbor,'prune_ratio':prune,'top_k':top}
            key=json.dumps(c,sort_keys=True)
            if key in seen:continue
            seen.add(key)
            m=evaluate(r,qs,c)['summary'];trials.append(dict(settings=c,summary=m))
        best=max(trials,key=lambda t:(t['summary']['leaderboard_score'],-t['summary']['estimated_tokens']));config=best['settings']
        (a.output/'trials.json').write_text(json.dumps(trials,indent=2))
    (a.output/'best-config.json').write_text(json.dumps(config,indent=2))
    report=evaluate(r,qs,config,True);report.update(settings=config,split=a.split,corpus_sha256=s.fingerprint)
    (a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['summary'],indent=2),flush=True)
if __name__=='__main__':main()
