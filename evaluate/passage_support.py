"""Development-trained numeric passage support filter with query-grouped CV.
Only model scores, metadata overlap, cost and neighborhood features enter inference.
"""
import numpy as np
from lexical_retrieval_v2 import terms

def matrix(r,v):
    ix=v['indices'];ce=1/(1+np.exp(-np.clip(np.array(v['ce'])/3,-30,30)));lex=np.array(v['lexical']);dense=np.array(v['dense'])
    qt=set(terms(v['query']));rows=[]
    anchors=[ix[int(np.argmax(row))] for row in ce]
    anchor_docs=[r.s.chunks[i]['doc_id'] for i in anchors]
    for j,i in enumerate(ix):
        chunk=r.s.chunks[i];head=set(terms(chunk['section_heading']));title=set(terms(chunk['source_title']))
        doc,pos=r.where[i]
        same=[ce[:,k].max() for k,kix in enumerate(ix) if r.s.chunks[kix]['doc_id']==doc]
        neighborhood=max((1/(1+abs(r.where[a][1]-pos)) for a in anchors if r.where[a][0]==doc),default=0)
        c=ce[:,j];l=lex[:,j];d=dense[:,j]
        rows.append([c.max(),c.mean(),c[0],np.mean(c>.5),l.max(),l.mean(),d.max(),d.mean(),
                     len(qt&head)/max(1,len(qt)),len(qt&title)/max(1,len(qt)),
                     np.log1p(r.s.costs[i]/100),anchor_docs.count(doc)/len(anchors),max(same),neighborhood,
                     float(doc in v.get('routed',[])),float(len(chunk['text'].split())<20)])
    return np.array(rows,dtype=float)
def fit(x,y,reg):
    mean=x.mean(axis=0);scale=x.std(axis=0)+.05;z=np.c_[(x-mean)/scale,np.ones(len(x))];w=np.zeros(z.shape[1])
    sample_weight=np.where(y==1,len(y)/(2*max(1,y.sum())),len(y)/(2*max(1,(y==0).sum())))
    for _ in range(450):
        p=1/(1+np.exp(-np.clip(z@w,-30,30)));grad=z.T@((p-y)*sample_weight)/len(y)+reg*w;grad[-1]-=reg*w[-1];w-=.2*grad
    return dict(mean=mean.tolist(),scale=scale.tolist(),weights=w.tolist(),regularization=reg)
def predict(x,state):
    z=np.c_[(x-np.array(state['mean']))/np.array(state['scale']),np.ones(len(x))]
    return 1/(1+np.exp(-np.clip(z@np.array(state['weights']),-30,30)))
