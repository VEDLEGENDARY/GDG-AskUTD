import json
from pathlib import Path
p=Path('evaluate/runs/reader-queue');p.mkdir(parents=True,exist_ok=True)
request=dict(system='You select evidence. Return only JSON. Pick the smallest set of passage IDs that answers every part of the question. Do not write an answer.',user='Question: Which desk issues a parking permit, and when does it close?\nPassages:\nA: The transport desk issues parking permits.\nB: The library opens at 8am.\nC: The transport desk closes at 5pm.\nD: The cafeteria accepts cash.\nReturn JSON with a selected list of string passage IDs. No explanation.',prefix='{"selected":[',max_tokens=32)
(p/'000-smoke.request.json').write_text(json.dumps(request),encoding='utf-8')
