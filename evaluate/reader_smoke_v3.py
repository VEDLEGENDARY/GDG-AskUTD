import json
from pathlib import Path
p=Path('evaluate/runs/reader-queue-v3');p.mkdir(parents=True,exist_ok=True)
req=dict(system='Select only passages that support every requested fact. Return JSON with answerable and selected keys.',user='Who issues parking permits, and when does that office close? A: The library opens at 8am. B: Lunch is served at noon. C: Transport issues parking permits. D: The transport office closes at 5pm. Choose the smallest sufficient set of passage letters.',max_tokens=60)
(p/'000-smoke.request.json').write_text(json.dumps(req))
