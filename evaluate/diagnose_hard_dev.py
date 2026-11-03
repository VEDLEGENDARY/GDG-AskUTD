import sys,json
from pathlib import Path
sys.path.insert(0,'evaluate')
from evaluate_chunks import *
p=Path('evaluate');chunks=read_chunks(Path('backend/data/chunks'));qs=read_questions(p/'questions.json',chunks,split='dev')
report=json.loads((p/'runs/hybrid-balanced/results.json').read_text())['suites']['questions.json']['dev']
for row in report['results']:
 if row['metrics']['complete_evidence']==0 or row['metrics']['abstention_correct']==0:
  q=row['question']; print('\nQUERY:',q['id'],q['query'])
  print('HITS:',[(h['chunk_id'],h['section_heading']) for h in row['retrieved']])
  for e in q['evidence']:
   if not any(supports(h,e) for h in row['retrieved']):
    gold=[c for c in chunks if supports(c,e)]
    print('MISSING:',e)
    print('SUPPORT:',[(c['chunk_id'],c['source_title'],c['section_heading'],c['text'][:400]) for c in gold[:3]])
