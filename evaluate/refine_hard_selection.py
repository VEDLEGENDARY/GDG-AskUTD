from pathlib import Path
p=Path('evaluate/hard_retrieval.py');s=p.read_text(encoding='utf-8')
s=s.replace("            j=choices[0];selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1\n        return", "            def adjacent(j):\n                doc,pos=self.where[indices[j]]\n                return any(self.where[indices[k]][0]==doc and abs(self.where[indices[k]][1]-pos)==1 for k in selected)\n            j=max(choices,key=lambda j:(row[j]+c.get('neighbor_boost',0)*adjacent(j),-j));selected.append(j);used+=self.s.costs[indices[j]];docs[self.s.chunks[indices[j]]['doc_id']]+=1\n        if c.get('prune_ratio',0):\n            for j in sorted(list(selected),key=lambda j:float(score[:,j].max())):\n                remaining=[k for k in selected if k!=j]\n                if not remaining:break\n                before=score[:,selected].max(axis=1);after=score[:,remaining].max(axis=1)\n                valid=np.isfinite(before)\n                if np.all(after[valid]>=before[valid]*c['prune_ratio']):selected.remove(j)\n        return")
# Refine previously promising settings instead of another large neural run.
a=s.index('        trials=[]\n        for w in [0.,.25,.5,.75,1.]:')
b=s.index('        best=max(trials',a)
s=s[:a]+'''        seeds=json.loads((ROOT/'runs/hard-facets-dev-v3/trials.json').read_text())
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
''' +s[b:]
p.write_text(s,encoding='utf-8')
