from instruction_retrieval import *
from evaluate_chunks import supports
chunks=read_chunks(ROOT.parent/'backend/data/chunks');qs=read_questions(ROOT/'questions.json',chunks,split='dev')
r=FacetRetriever(SemanticRetriever(chunks,ROOT/'runs/semantic-hard/cache',None),ROOT/'runs/hard-facets-cache-v2');state=json.loads((ROOT/'runs/hard-support-dev/support-model.json').read_text())
total=missing=0
for q in qs:
 if q['unanswerable']:continue
 packet,aliases,base,reason=prepare_packet(r,q['query'],state)
 for e in q['evidence']:
  total+=1
  if not any(supports(chunks[i],e) for i in aliases.values()):missing+=1;print('Missing packet group:',q['id'])
print('Development packet coverage',total-missing,'/',total)
