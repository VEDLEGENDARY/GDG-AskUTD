import os,sys,time,json
from pathlib import Path
import numpy
sys.path.insert(0,str(Path('evaluate/.llm-deps').resolve()))
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
import torch
from transformers import AutoTokenizer,AutoModelForCausalLM
torch.set_num_threads(8)
p=Path.home()/'.cache/huggingface/hub/models--meta-llama--Llama-3.2-1B-Instruct/snapshots/9213176726f574b556790deb65791e0c5aa438b6'
t=AutoTokenizer.from_pretrained(str(p),local_files_only=True)
m=AutoModelForCausalLM.from_pretrained(str(p),local_files_only=True,torch_dtype=torch.float32,attn_implementation='eager').eval()
messages=[dict(role='system',content='Return only JSON. Select passages answering every part of the question.'),dict(role='user',content='Which desk issues permits and when does it close? A: Transport desk issues permits. B: Library opens 8am. C: Transport desk closes 5pm. Return JSON like {"selected":["A","C"]}.')]
x=t.apply_chat_template(messages,add_generation_prompt=True,return_tensors='pt');print('input bos count',int((x==128000).sum()),flush=True);start=time.perf_counter()
with torch.inference_mode():y=m.generate(x,max_new_tokens=35,do_sample=False,temperature=None,top_p=None,pad_token_id=t.eos_token_id)
print(t.decode(y[0,x.shape[1]:],skip_special_tokens=True),time.perf_counter()-start,flush=True)
