"""Local persistent reader. Queue files contain prompts only, never executable code."""
import json,time
from pathlib import Path
from instruction_model import InstructionModel
root=Path(__file__).resolve().parent/'runs/reader-queue-v4';root.mkdir(parents=True,exist_ok=True)
model=InstructionModel(small=False,quantize=True)
(root/'READY').write_text('ready')
while not (root/'STOP').exists():
 for path in sorted(root.glob('*.request.json')):
  result=path.with_name(path.name.replace('.request.json','.result.json'))
  if result.exists():continue
  try:
   item=json.loads(path.read_text(encoding='utf-8'))
   response,elapsed=model.generate(item['system'],item['user'],min(160,max(1,item.get('max_tokens',64))),item.get('prefix',''))
   result.write_text(json.dumps(dict(response=response,elapsed=elapsed)),encoding='utf-8');print(path.stem,elapsed,flush=True)
  except Exception as e:result.write_text(json.dumps(dict(error=str(e))),encoding='utf-8')
 time.sleep(.25)
