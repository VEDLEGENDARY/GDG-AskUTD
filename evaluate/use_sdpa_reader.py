from pathlib import Path
p=Path('evaluate/instruction_model.py');s=p.read_text(encoding='utf-8').replace("attn_implementation='eager'","attn_implementation='sdpa'");p.write_text(s,encoding='utf-8')
import json
q=Path('evaluate/runs/reader-queue-v2')
smoke=dict(system='Select evidence. Return only JSON with answerable and selected keys. Do not answer in prose.',user='Which desk issues a permit, and when does it close? A: The library opens 8am. B: The transport desk issues permits. C: The cafe serves lunch. D: The transport desk closes 5pm. Select the smallest set of passage IDs covering both facts.',max_tokens=40)
(q/'000-smoke.request.json').write_text(json.dumps(smoke))
