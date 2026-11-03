"""Local instruction model, offline model loading, deterministic JSON inference."""
import os,sys,time,json,re
from pathlib import Path
# Preserve the system's NumPy ABI when loading isolated inference dependencies.
import numpy
sys.path.insert(0,str(Path(__file__).resolve().parent/'.llm-deps'))
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
from transformers import AutoTokenizer,AutoModelForCausalLM,StoppingCriteria,StoppingCriteriaList
ROOT=Path(__file__).resolve().parent
MODEL=Path.home()/'.cache/huggingface/hub/models--meta-llama--Llama-3.2-3B-Instruct/snapshots/0cb88a4f764b7a12671c53f0838cd831a0843b95'
class InstructionModel:
 def __init__(self,small=False,quantize=False):
  torch.set_num_threads(8);torch.set_num_interop_threads(1);start=time.perf_counter();print('Loading local instruction model',flush=True)
  model_path=Path.home()/'.cache/huggingface/hub/models--meta-llama--Llama-3.2-1B-Instruct/snapshots/9213176726f574b556790deb65791e0c5aa438b6' if small else MODEL
  self.tokenizer=AutoTokenizer.from_pretrained(str(model_path),local_files_only=True)
  model=AutoModelForCausalLM.from_pretrained(str(model_path),torch_dtype=torch.float32,local_files_only=True,attn_implementation='sdpa').eval()
  if quantize:
   print('Applying per-channel CPU quantization',flush=True)
   modules={name:torch.ao.quantization.per_channel_dynamic_qconfig for name,module in model.named_modules() if isinstance(module,torch.nn.Linear) and name!='lm_head'}
   model=torch.ao.quantization.quantize_dynamic(model,modules,dtype=torch.qint8,inplace=True)
  self.model=model
  print(f'Instruction model ready in {time.perf_counter()-start:.1f}s',flush=True)
 def generate(self,system,user,max_tokens=150,prefix=""):
  messages=[dict(role='system',content=system),
   dict(role='user',content='Which desk issues building keys? A: Lunch is at noon. B: Facilities issues keys. Select evidence.'),
   dict(role='assistant',content='{"answerable":true,"selected":["B"]}'),
   dict(role='user',content='When does the shuttle leave and where does it stop? A: The library is open. B: The shuttle departs at 8am. C: Lunch is served at noon. D: It stops at East Gate.'),
   dict(role='assistant',content='{"answerable":true,"selected":["B","D"]}'),
   dict(role='user',content='Was my personal application approved? A: Applications are reviewed within ten days.'),
   dict(role='assistant',content='{"answerable":false,"selected":[]}'),
   dict(role='user',content=user)]
  text=self.tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
  text+=prefix
  inputs=self.tokenizer(text,return_tensors='pt',add_special_tokens=False);start=time.perf_counter()
  tokenizer=self.tokenizer;prompt_length=inputs['input_ids'].shape[1]
  class StopJSON(StoppingCriteria):
   def __call__(self,input_ids,scores,**kwargs):
    text=prefix+tokenizer.decode(input_ids[0,prompt_length:],skip_special_tokens=True)
    start=text.find('{')
    if start<0:return False
    try:json.JSONDecoder().raw_decode(text[start:]);return True
    except ValueError:return False
  with torch.inference_mode():out=self.model.generate(**inputs,num_logits_to_keep=1,stopping_criteria=StoppingCriteriaList([StopJSON()]),max_new_tokens=max_tokens,do_sample=False,temperature=None,top_p=None,pad_token_id=self.tokenizer.eos_token_id)
  response=self.tokenizer.decode(out[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True)
  return prefix+response,time.perf_counter()-start
 def json(self,system,user,max_tokens=150):
  text,elapsed=self.generate(system,user,max_tokens)
  match=re.search(r'\{[\s\S]*\}',text)
  try:return json.loads(match.group()),elapsed,text
  except (ValueError,AttributeError):return None,elapsed,text
if __name__=='__main__':
 m=InstructionModel();answer,elapsed,raw=m.json('You rewrite university questions into independent search queries. Do not answer. Return JSON with a searches list of at most three short strings.', 'I am passing but an emergency stopped me after three quarters of the coursework. What temporary grade could the instructor use, what is the normal completion limit, and what happens if I miss it?',120)
 print(json.dumps(dict(answer=answer,elapsed=elapsed,raw=raw),indent=2),flush=True)
