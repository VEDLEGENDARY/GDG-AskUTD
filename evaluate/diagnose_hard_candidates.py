import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'evaluate');from evaluate_chunks import *
c=read_chunks(Path('backend/data/chunks'));q=read_questions(ROOT/'questions.json',c,split='dev')
for x in q:
 if x['unanswerable']:continue
 path=ROOT/'runs/hybrid-all/hard-cache'/(hashlib.sha256(x['query'].encode()).hexdigest()+'.json')
 scores={int(i):v for i,v in json.loads(path.read_text()).items()} if path.exists() else {}
 missing=[(e,[i for i,z in enumerate(c) if supports(z,e)]) for e in x['evidence'] if not any(i in scores for i,z in enumerate(c) if supports(z,e))]
 if missing:print('POOL MISSING',x['id'],[(c[i]['chunk_id'],e) for e,ids in missing for i in ids])
 if x['id']=='dev-hard-unfinished-course':
  print('INCOMPLETE TOP',[(c[i]['chunk_id'],round(v,2)) for i,v in sorted(scores.items(),key=lambda t:-t[1])[:10]])
  print('INCOMPLETE GOLD',[(z['chunk_id'],scores.get(i)) for i,z in enumerate(c) if any(supports(z,e) for e in x['evidence'])])
