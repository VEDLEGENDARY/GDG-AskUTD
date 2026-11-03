from pathlib import Path
p=Path('evaluate/instruction_retrieval.py');s=p.read_text(encoding='utf-8').replace('for offset in [-1,1,-2,2]:','for offset in [1,2,-1,-2]:')
s=s.replace("hashlib.sha256((SYSTEM+q['query']).encode()).hexdigest()", "hashlib.sha256((s.fingerprint+json.dumps(packet,sort_keys=True)).encode()).hexdigest()")
p.write_text(s,encoding='utf-8')
