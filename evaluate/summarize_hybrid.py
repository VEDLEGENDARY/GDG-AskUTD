import json,sys
from pathlib import Path
sys.path.insert(0,'evaluate')
root=Path('evaluate'); report=json.loads((root/'runs/hybrid-balanced/results.json').read_text())
labels={'starter_questions.json':'Starter test (10)','realistic_questions.json':'Realistic test (9)','audit_questions.json':'Audit (15)','questions.json':'Repository hard test (32)'}
lines=['# Balanced hybrid retrieval: results and limits','',
'**The 90–95 target has not been reached across all groups.** The balanced configuration improves the weaker sets, but the hard repository benchmark remains substantially below the target. All scores below use the unchanged reference evidence and weighted leaderboard.',
'', '| Test set | Balanced score |','| --- | ---: |']
for name,label in labels.items():lines.append(f"| {label} | {report['suites'][name]['test']['summary']['leaderboard_score']:.2f} |")
rows=report['suites']['realistic_questions.json']['test']['results']
lines+=['','## Realistic requests by difficulty','', '| Difficulty | Complete evidence |','| --- | ---: |']
for category in ['easy','medium','hard']:
 group=[r for r in rows if r['question']['category']==category]
 if group:lines.append(f"| {category} | {sum(r['metrics']['complete_evidence'] for r in group)}/{len(group)} |")
lines+=['','These difficulty rows report complete-evidence counts, not the weighted leaderboard. Small groups make percentages unstable; one hard miss changes that group by 25 percentage points.',
'', '## Implementation','',
'- Added local semantic candidate retrieval with all-MiniLM-L6-v2 and MS MARCO MiniLM cross-encoder passage reranking, using already cached ONNX models.',
'- Combined semantic scores with lexical/metadata coverage and clause-aware retrieval. Additional passages must still respect the 900 estimated-token budget and three-chunk per-document cap.',
'- Added a private-record detector trained only on development question labels, with five-fold stratified calibration, explicit public/procedural safeguards, and frozen coefficients for unseen queries.',
'- Selected one balanced setting by the lowest development-suite score, then average development score. All test results are reported; the audit has no development split and did not select settings.',
'- No question IDs, reference phrases or document relevance labels enter passage retrieval. Answerability training uses only the dev unanswerable flag.',
'', '## Evidence and limitations','',
'The starter, realistic and audit suites retain the earlier 1,028-chunk Lokesh corpus in evaluate/exports/previous-lokesh. The repository hard suite uses the current 2,632 chunks from 118 files in backend/data/chunks. Scores are separate evaluations, not one pooled estimate. Reference labels and chunk contents were not edited to improve scores.',
'', 'All hard benchmark questions were checked for reference-evidence feasibility within 900 tokens and up to six passages; none were intrinsically infeasible. The remaining losses therefore cannot be dismissed as merely an impossible token limit. They include incomplete multi-part evidence and unsupported personal facts that the answerability detector still accepts.',
'', 'The small earlier test sets have already been inspected in this chat and are regression checks, not untouched generalization benchmarks. Questions are author-written rather than authentic student logs. The local WordPiece implementation targets these cached English uncased BERT tokenizer specifications; multilingual/special-token parity has not been established. Models encode at most 256 tokens per candidate representation and rerank up to 512 combined tokens, which can miss facts deep in long passages.',
'', 'A separate configuration emphasizing the earlier suites is retained under runs/hybrid-final (87.19 starter, 87.86 realistic, 92.27 audit, 41.81 hard test). It was not chosen as the balanced recommendation because its weakest development-suite result was lower. Keeping several profiles does not establish that any profile reaches 90 everywhere.',
'', '## Run a new question','',
'This machine has a working Python 3.10 installation with NumPy and ONNX Runtime. The bundled Python used earlier lacks ONNX Runtime. The model snapshots are read from the local Hugging Face cache; no model download or API call was made.',
'', '```powershell',
'& "$env:LOCALAPPDATA\\Programs\\Python\\Python310\\python.exe" evaluate/query_hybrid.py --query "I am a graduate student. How do I drop a class before Census Day?"',
'```',
'', 'The CLI loads hybrid.config.json and hybrid.detector.json, evaluates new questions without fitting on reference labels, and returns candidate evidence or an abstention reason. It does not generate a final answer or perform university account actions. Neural inference is slower than the earlier lexical-only exercise; cached features speed repeated evaluation.',
'', '## Checks and artifacts','',
'- Eight semantic and seven hybrid tests pass (15 new tests).',
'- The existing full evaluator suite still fails with the existing config.example.json (four failures and one error, including corpus-feasibility checks and synthetic retrieval cases). The 40-word maximum filter and strict threshold affect those tests. Existing config, evaluator, tests and search edits were left intact; no claim is made that the full repo test suite is green.',
'- Frozen settings: hybrid.config.json; answerability coefficients/calibration: hybrid.detector.json.',
'- Full evidence per question: runs/hybrid-balanced/results.json.',
'- Model-only comparisons: runs/semantic-student/results.json and runs/semantic-hard/results.json.',
'- Earlier and focused hybrid profiles and all dev settings comparisons remain under runs/.',
'', '## Hard-test misses','']
for row in report['suites']['questions.json']['test']['results']:
 m=row['metrics']
 if m['complete_evidence']==0 or m['abstention_correct']==0:
  lines.append(f"- {row['question']['id']}: {row['question']['query']}")
(root/'HYBRID_RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:23]))
