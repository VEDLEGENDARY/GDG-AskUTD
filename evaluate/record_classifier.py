"""Development-only calibrated private-record detector using sentence embeddings.
No test labels are used for fitting or calibration.
"""
import hashlib,json,re
import numpy as np

def features(queries,embeddings):
    flags=[]
    for q in queries:
        text=q.lower()
        flags.append([bool(re.search(pattern,text)) for pattern in [r'\bmy\b',r'\b(?:i|me)\b',r'\b(?:exact|actual|personal|individual)\b',r'\b(?:already|currently|corrected)\b',r'\b(?:approved|accepted|assigned|scheduled)\b',r'\b(?:if|suppose|assuming)\b',r'\b(?:rule|policy|requirement|minimum)\b',r'\b(?:how can|how do|where can|where do)\b',r'\b(?:203\d|204\d)\b']])
    return np.hstack([embeddings*3,np.array(flags,dtype=float),np.ones((len(queries),1))])
def fit(x,y,penalty):
    w=np.zeros(x.shape[1]);weight=np.where(y==1,len(y)/(2*max(1,y.sum())),len(y)/(2*max(1,(y==0).sum())))
    for _ in range(700):
        p=1/(1+np.exp(-np.clip(x@w,-30,30)))
        grad=x.T@((p-y)*weight)/len(y)+penalty*w;grad[-1]-=penalty*w[-1]
        w-=.25*grad
    return w
class RecordDetector:
    def __init__(self,models,suites,path):
        self.models=models;self.probabilities={};self.path=path
        all_queries=list(dict.fromkeys(q['query'] for _,qs in suites.values() for q in qs))
        emb=models.embed(all_queries);self.lookup=dict(zip(all_queries,emb))
        examples={q['query']:int(q['unanswerable']) for _,qs in suites.values() for q in qs if q['split']=='dev'}
        names=list(examples);y=np.array(list(examples.values()));x=features(names,np.array([self.lookup[n] for n in names]))
        rng=np.random.default_rng(481);fold=np.zeros(len(y),dtype=int)
        for value in [0,1]:
            ids=np.where(y==value)[0];rng.shuffle(ids)
            for i,j in enumerate(ids):fold[j]=i%5
        options=[]
        for reg in [.01,.05,.2]:
            probs=np.zeros(len(y))
            for k in range(5):
                mask=fold!=k;w=fit(x[mask],y[mask],reg);probs[~mask]=1/(1+np.exp(-np.clip(x[~mask]@w,-30,30)))
            for cutoff in [.3,.4,.5,.6,.7]:
                pred=probs>=cutoff
                balanced=((pred[y==1]).mean()+(~pred[y==0]).mean())/2
                options.append(dict(reg=reg,cutoff=cutoff,balanced_accuracy=float(balanced),false_rejections=int(((pred==1)&(y==0)).sum())))
        best=max(options,key=lambda t:(t['balanced_accuracy'],-t['false_rejections']))
        self.cutoff=best['cutoff'];self.w=fit(x,y,best['reg'])
        xx=features(all_queries,emb);p=1/(1+np.exp(-np.clip(xx@self.w,-30,30)));self.probabilities=dict(zip(all_queries,p.tolist()))
        path.write_text(json.dumps(dict(calibration=best,training_questions=len(y),training_query_sha256=hashlib.sha256(json.dumps(names).encode()).hexdigest(),weights=self.w.tolist(),threshold=self.cutoff),indent=2))
    @classmethod
    def load(cls,models,path):
        obj=object.__new__(cls);state=json.loads(path.read_text());obj.models=models;obj.w=np.array(state['weights']);obj.cutoff=state['threshold'];obj.probabilities={};return obj
    def reason(self,query):
        # A learned private-record detector must not reject ordinary public questions.
        personal=re.search(r'\b(my|mine|me|i|our|we)\b',query,re.I)
        future=re.search(r'\b(?:203\d|204\d|future|next year)\b',query,re.I)
        procedural=re.search(r'\b(?:how|where) (?:can|do|should) i\b',query,re.I)
        if (not personal and not future) or procedural:return None
        if query not in self.probabilities:
            x=features([query],self.models.embed([query]));self.probabilities[query]=float(1/(1+np.exp(-np.clip(x@self.w,-30,30)[0])))
        if self.probabilities[query]>=self.cutoff:return 'Development-calibrated detector: request needs individual records or unsupported future information'
        return None
