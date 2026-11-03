from pathlib import Path
p=Path('evaluate/instruction_model.py');s=p.read_text(encoding='utf-8').replace('def __init__(self,small=False):','def __init__(self,small=False,quantize=False):')
s=s.replace('  self.model=model\n', "  if quantize:\n   print('Applying per-channel CPU quantization',flush=True)\n   modules={name:torch.ao.quantization.per_channel_dynamic_qconfig for name,module in model.named_modules() if isinstance(module,torch.nn.Linear) and name!='lm_head'}\n   model=torch.ao.quantization.quantize_dynamic(model,modules,dtype=torch.qint8,inplace=True)\n  self.model=model\n")
p.write_text(s,encoding='utf-8')
p=Path('evaluate/local_reader_worker.py');s=p.read_text(encoding='utf-8').replace('reader-queue-v3','reader-queue-v4').replace('InstructionModel(small=False)','InstructionModel(small=False,quantize=True)');p.write_text(s,encoding='utf-8')
p=Path('evaluate/instruction_retrieval.py');s=p.read_text(encoding='utf-8').replace('reader-queue-v3','reader-queue-v4').replace('reader-v3-','reader-v4-');p.write_text(s,encoding='utf-8')
import shutil
q=Path('evaluate/runs/reader-queue-v4');q.mkdir(parents=True,exist_ok=True)
shutil.copyfile('evaluate/runs/reader-queue-v3/000-smoke.request.json',q/'000-smoke.request.json')
