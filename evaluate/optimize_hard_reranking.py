from pathlib import Path
p=Path('evaluate/hard_retrieval.py');s=p.read_text(encoding='utf-8-sig')
s=s.replace('PROGRAMS={', '''class FastModels(Models):
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

PROGRAMS={''')
s=s.replace("        for f,(text,doc) in enumerate(scoped):\n            ce.append(self.s.models.rerank(text,[self.s.texts[i] for i in indices]))", "        for f,(text,doc) in enumerate(scoped):\n            if doc:\n                chosen=[j for j,i in enumerate(indices) if self.s.chunks[i]['doc_id']==doc]\n            else:\n                preliminary=.6*dense[f,indices]+.4*np.array(lexical)[f,indices]\n                chosen=np.argsort(-preliminary)[:20].tolist()\n            values=[-12.]*len(indices)\n            reranked=self.s.models.rerank(text,[self.s.texts[indices[j]] for j in chosen])\n            for j,value in zip(chosen,reranked):values[j]=value\n            ce.append(values)")
s=s.replace('models=Models();s=SemanticRetriever','models=FastModels();s=SemanticRetriever')
s=s.replace("ROOT/'runs/hard-facets-cache'", "ROOT/'runs/hard-facets-cache-v2'")
p.write_text(s,encoding='utf-8')
