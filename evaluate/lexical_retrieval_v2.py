"""Evidence retrieval v2: morphology, query expansion, clause coverage, abstention.
The retriever has no access to question IDs, reference snippets, or labels.
"""
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse, hashlib, json, math, os, random, re, time
os.environ['OPENBLAS_NUM_THREADS']='1'
import numpy as np
from evaluate_chunks import Settings, cost, grade, metadata, normalize, read_chunks, read_questions, summarize

# General vocabulary aliases. No document IDs or benchmark answers are encoded.
ALIASES = {
 'f1':'f', 'j1':'j', 'masters':'master', 'finish':'graduate', 'check':'verify', 'adviser':'advisor', 'submission':'submit', 'submitted':'submit', 'graduation':'graduate', 'waive':'exemption', 'exempt':'exemption', 'money back':'refund', 'stop paying':'non payment', 'continuously':'continuous', 'shot':'vaccination', 'jab':'vaccination', 'inoculation':'vaccination',
 'compulsory':'mandatory', 'required':'mandatory', 'permission':'approval',
 'drop':'withdrawal', 'dropping':'withdrawal', 'withdraw':'withdrawal',
 'undergrad':'undergraduate', 'grad':'graduate', 'dorm':'housing', 'dormitory':'housing',
 'cost':'fee', 'price':'fee', 'credits':'hours', 'credit':'hours', 'email':'email',
 'scholarships':'scholarship', 'aid':'financial', 'enrolled':'enrollment',
 'enrolment':'enrollment', 'sign up':'registration', 'register':'registration',
 'phone':'telephone', 'classes':'class', 'dropped':'withdrawal', 'number':'number', 'tuition reimbursement':'refund',
}
STOP=set('hey hi im m gotta wanna checklist draft make give write create two part sent already actually went through here gets include explain usual normal just somebody thanks please am doing take keep get a an the is are was were be to of in on for and or with by at i my do does how what which can should could would will where who when it its if as from must need look just before after please tell me about much many'.split())
def stem(t):
    if len(t)>5 and t.endswith('ies'): return t[:-3]+'y'
    if len(t)>5 and t.endswith('ing'):
        base=t[:-3]
        return base[:-1] if len(base)>2 and base[-1]==base[-2] else base
    if len(t)>5 and t.endswith('ed'): return t[:-2]
    if len(t)>4 and t.endswith('s') and not t.endswith(('ss','us')): return t[:-1]
    return t

def terms(text):
    text=normalize(text)
    # Canonicalize both sides so aliases do not dilute query coverage.
    text=re.sub(r'\btake (?:a |the )?(?:semester|fall|spring|summer|year) off\b','leave absence',text)
    for phrase,alias in sorted(ALIASES.items(),key=lambda item:-len(item[0])):
        text=re.sub(r'\b'+re.escape(phrase)+r'\b',alias,text)
    return [stem(t) for t in text.split() if t not in STOP]

def abstention_reason(query, corpus_years):
    q=normalize(query)
    # Executing a university account change requires an authorized transaction tool.
    if re.search(r'^(?:please |actually )?(?:withdraw me|drop my|enroll me|register me|submit my|send my)\b',q):
        return 'Requires an authorized university account action; retrieval cannot perform it'
    # Requests for a private record/contact need a personalized data source.
    private_contact = re.search(r'\b(personal|private)\b',q) and re.search(r'\b(mobile|cell|cellphone|home address|home phone)\b',q)
    own_value = re.search(r'\b(my|mine)\b',q) and re.search(r'\b(exact|exactly|individual|personal|current)\b',q)
    own_value = own_value and re.search(r'\b(balance|refund|gpa|grade|status|decision|schedule|salary)\b',q)
    public_policy=re.search(r'\b(policy|policies|rule|rules|rights|minimum|eligibility)\b',q)
    if (private_contact or own_value) and not public_policy: return 'Requires private or personalized records absent from this public-document corpus'
    prediction = re.search(r'\b(will|predict|forecast)\b',q) and re.search(r'\b(tomorrow|future|next week|next year)\b',q)
    if prediction and re.search(r'\b(approved|accepted|decision|outcome|change|say|happen)\b',q):
        return 'Asks for a future outcome that static public documents cannot establish'
    years=set(re.findall(r'\b(?:19|20)\d{2}\b',q))
    if years and not years.issubset(corpus_years) and re.search(r'\b(catalog|degree plan|policy|policies)\b',q):
        return 'Requested policy/catalog year is absent from the supplied corpus'
    return None

@dataclass
class V2Settings:
    bm25_weight: float=.55
    metadata_weight: float=.25
    coverage_weight: float=.20
    diversity: float=.2
    min_coverage: float=.1
    relative_cutoff: float=.65
    min_score: float=.1
    length_penalty: float=.05
    max_chunks: int=4
    max_per_document: int=3
    context_budget: int=900
    extra_chunks: int=0
    def validate(self):
        for k,v in asdict(self).items():
            if k in ('max_chunks','max_per_document','context_budget','extra_chunks'):
                if type(v) is not int or v<0 or (k!='extra_chunks' and v==0): raise ValueError(k)
            elif not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1: raise ValueError(k)
        if self.context_budget>900: raise ValueError('context_budget cap is 900')

class ImprovedRetriever:
    def __init__(self,chunks):
        self.chunks=chunks; self.docs=[c['doc_id'] for c in chunks]; self.n=len(chunks)
        self.counts=[Counter(terms(c['text'])) for c in chunks]
        self.meta=[set(terms(metadata(c))) for c in chunks]
        self.df=Counter(t for counts in self.counts for t in counts)
        self.idf={t:math.log(1+(self.n-n+.5)/(n+.5)) for t,n in self.df.items()}
        self.lengths=np.array([sum(c.values()) for c in self.counts],dtype=float)
        self.avg=float(self.lengths.mean()) or 1
        self.costs=np.array([cost(c) for c in chunks])
        self.full=[set(c)|m for c,m in zip(self.counts,self.meta)]
        self.years=[set(re.findall(r'\b(?:19|20)\d{2}\b',metadata(c)+' '+c['text'])) for c in chunks]
        self.corpus_years=set().union(*self.years)
        joint_df=Counter(t for row in self.full for t in row)
        self.cover_idf={t:math.log(1+(self.n-n+.5)/(n+.5)) for t,n in joint_df.items()}
        self.cache={}; self.pairs={}
    def similarity(self,a,b):
        key=min(a,b),max(a,b)
        if key not in self.pairs:
            x,y=self.full[a],self.full[b]
            self.pairs[key]=len(x&y)/max(1,len(x|y))
        return self.pairs[key]
    def prepare(self,query):
        if query in self.cache: return self.cache[query]
        reason=abstention_reason(query,self.corpus_years)
        # Keep named pairs such as F and J intact; split only independent requests.
        clauses=[x.strip() for x in re.split(r'[?;]|,\s*(?=(?:what|how|which|who|where|whether)\b)|\band\s+(?=(?:how|who|what|which|where|are|is|does|do|can|whether|the usual|the normal|the rule)\b)',query,flags=re.I) if x.strip()]
        if not clauses: clauses=[query]
        range_pattern=r'\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b'
        ranges=list(dict.fromkeys(re.findall(range_pattern,query)))
        if len(ranges)>1 and re.search(r'\b(compare|difference|versus|between)\b',query,re.I):
            clauses=[re.sub(range_pattern,lambda m:m.group() if m.group()==target else '',query) for target in ranges]
        # A leading shared context stays available through metadata scoring.
        global_years=set(re.findall(r'\b(?:19|20)\d{2}\b',query))
        year_ranges=re.findall(r'\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b',query)
        one_edition=len(year_ranges)==1 or len(global_years)==1
        arrays=[]
        for clause in clauses:
            if re.search(r'\b(this|that|it|exception)\b',clause,re.I) and len(terms(clause))<7:
                clause=clause+' '+query
            ts=set(terms(clause)); tt=sorted(ts)
            idf=np.array([self.idf.get(t,math.log(1+(self.n+.5)/.5)) for t in tt])
            tf=np.array([[c[t] for t in tt] for c in self.counts],dtype=float)
            adj=1.2*(.25+.75*self.lengths/self.avg)
            bm=((tf*2.2/(tf+adj[:,None]))*idf).sum(axis=1)
            bm=bm/(float(bm.max()) or 1)
            meta=np.array([len(ts&m)/max(1,len(ts)) for m in self.meta])
            cover_weights={t:self.cover_idf.get(t,math.log(1+(self.n+.5)/.5)) for t in ts}
            coverage=np.array([sum(cover_weights[t] for t in ts&row)/max(.0001,sum(cover_weights.values())) for row in self.full])
            # For a single requested catalog year, avoid adjacent-year degree plans.
            allowed=np.ones(self.n,dtype=bool)
            clause_years=set(re.findall(r'\b(?:19|20)\d{2}\b',clause))
            clause_ranges=re.findall(range_pattern,clause)
            if len(clause_ranges)==1 or len(clause_years)==1:
                for i,c in enumerate(self.chunks):
                    title_years=set(re.findall(r'\b(?:19|20)\d{2}\b',metadata(c)))
                    if title_years and not clause_years.issubset(title_years): allowed[i]=False
            arrays.append((bm,meta,coverage,allowed))
        value=(reason,arrays); self.cache[query]=value; return value
    def retrieve(self,query,s):
        reason,arrays=self.prepare(query)
        if reason: return [],reason
        scores=[]
        total=max(.0001,s.bm25_weight+s.metadata_weight+s.coverage_weight)
        for bm,meta,coverage,allowed in arrays:
            score=(s.bm25_weight*bm+s.metadata_weight*meta+s.coverage_weight*coverage)/total
            score=score-s.length_penalty*np.log1p(self.costs/100)
            score=np.where(allowed&(coverage>=s.min_coverage)&(score>=s.min_score),score,-np.inf)
            scores.append(score)
        selected=[]; used=0; counts=Counter()
        # One best result per independent clause, then optional extras.
        for selection_round,score in enumerate(scores+[np.max(scores,axis=0)]*s.extra_chunks):
            if len(selected)>=s.max_chunks: break
            if selection_round<len(scores) and selected and any(np.isfinite(score[i]) and score[i]>=np.max(score)*s.relative_cutoff for i in selected): continue
            order=np.argsort(-score,kind='stable')[:80]
            candidates=[int(i) for i in order if np.isfinite(score[i]) and i not in selected and
                        score[i]>=np.max(score)*s.relative_cutoff and counts[self.docs[i]]<s.max_per_document and
                        used+int(self.costs[i])<=s.context_budget]
            if not candidates: continue
            best=max(candidates,key=lambda i:(score[i]-s.diversity*max((self.similarity(i,j) for j in selected),default=0),-i))
            selected.append(best); used+=int(self.costs[best]); counts[self.docs[best]]+=1
        hits=[{**self.chunks[i],'estimated_tokens':int(self.costs[i])} for i in selected]
        return hits,None

def evaluate(r,questions,s,full=False):
    rows=[]
    for q in questions:
        hits,reason=r.retrieve(q['query'],s)
        row=dict(metrics=grade(q,hits))
        if full: row.update(question=q,retrieved=hits,abstention_reason=reason)
        rows.append(row)
    result=dict(summary=summarize(rows))
    if full: result['results']=rows
    return result

SPACE={'bm25_weight':(0,1),'metadata_weight':(0,1),'coverage_weight':(0,1),'diversity':(0,.5),'min_coverage':(0,.5),
'relative_cutoff':(.3,1),'min_score':(0,.7),'length_penalty':(0,.25),
'max_chunks':(2,6),'max_per_document':(1,4),'context_budget':(300,900),'extra_chunks':(0,2)}
INTS={'max_chunks','max_per_document','context_budget','extra_chunks'}
def random_config(rng):
    return {k:rng.randint(lo,hi) if k in INTS else round(rng.uniform(lo,hi),5) for k,(lo,hi) in SPACE.items()}
def rank(item): return item[1]['summary']['leaderboard_score'],-item[1]['summary']['estimated_tokens']
def search(args):
    chunks=read_chunks(args.chunks)
    # Only development labels are passed to fitness evaluation.
    questions=[q for q in read_questions(args.questions,chunks) if q['split']=='dev']
    r=ImprovedRetriever(chunks)
    for q in questions: r.prepare(q['query'])
    rng=random.Random(args.seed); cache={}; population=[asdict(V2Settings())]+[random_config(rng) for _ in range(31)]
    best=None; generations=0; history=[]; start=time.perf_counter()
    while time.perf_counter()-start<args.seconds:
        ranked=[]
        for c in population:
            if time.perf_counter()-start>=args.seconds: break
            key=json.dumps(c,sort_keys=True)
            if key not in cache: cache[key]=evaluate(r,questions,V2Settings(**c))
            item=c,cache[key]; ranked.append(item)
            if best is None or rank(item)>rank(best):
                best=item; history.append(dict(elapsed=time.perf_counter()-start,generation=generations,score=rank(best)[0]))
        if not ranked: break
        ranked.sort(key=rank,reverse=True); population=[c for c,_ in ranked[:5]]; generations+=1
        while len(population)<32:
            if rng.random()<.15: population.append(random_config(rng)); continue
            a=max(rng.choices(ranked,k=3),key=rank)[0]; b=max(rng.choices(ranked,k=3),key=rank)[0]
            c={k:rng.choice([a[k],b[k]]) for k in a}
            for k,(lo,hi) in SPACE.items():
                if rng.random()<.3:
                    v=min(hi,max(lo,c[k]+rng.gauss(0,.15)*(hi-lo)))
                    c[k]=round(v) if k in INTS else round(v,5)
            population.append(c)
    args.output.mkdir(parents=True,exist_ok=False)
    config=best[0]; s=V2Settings(**config); s.validate()
    save=lambda name,obj:(args.output/name).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
    save('best-config.json',config)
    # Freeze selected configuration before scoring the previously used test split.
    all_questions=read_questions(args.questions,chunks)
    report=dict(settings=config,seed=args.seed,generations=generations,unique_evaluations=len(cache),
      actual_seconds=time.perf_counter()-start,improvements=history,scoring='unchanged original leaderboard',
      corpus_sha256=hashlib.sha256(json.dumps(chunks,sort_keys=True).encode()).hexdigest())
    for split in ('dev','test'):
        report[split]=evaluate(r,[q for q in all_questions if q['split']==split],s,True)
    save('results.json',report)
    print(json.dumps({k:report[k]['summary'] for k in ('dev','test')},indent=2),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--chunks',type=Path,default=Path(__file__).parent/'corpora/lokesh')
    p.add_argument('--questions',type=Path,default=Path(__file__).parent/'questions.json'); p.add_argument('--seconds',type=float,default=30)
    p.add_argument('--seed',type=int,default=2026); p.add_argument('--output',type=Path,default=Path(__file__).parent/'runs/v2')
    search(p.parse_args())
if __name__=='__main__': main()
