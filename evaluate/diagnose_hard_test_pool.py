import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,'evaluate')
from evaluate_chunks import *
c=read_chunks(Path('backend/data/chunks'));qs=read_questions(ROOT/'questions.json',c,split='test')
miss=[];total=0
for q in qs:
 if q['unanswerable']:continue
 v=json.loads((ROOT/'runs/hard-facets-cache-v2'/(hashlib.sha256(q['query'].encode()).hexdigest()+'.json')).read_text())
 for e in q['evidence']:
  total+=1
  if not any(supports(c[i],e) for i in v.get('indices',[])):miss.append(q['id'])
print('test candidate evidence coverage:',total-len(miss),'/',total,'missing queries',miss)
