from pathlib import Path
p=Path('evaluate/instruction_model.py');s=p.read_text(encoding='utf-8')
s=s.replace('from transformers import AutoTokenizer,AutoModelForCausalLM','from transformers import AutoTokenizer,AutoModelForCausalLM,StoppingCriteria,StoppingCriteriaList')
s=s.replace("  messages=[dict(role='system',content=system),dict(role='user',content=user)]",'''  messages=[dict(role='system',content=system),
   dict(role='user',content='Which desk issues building keys? A: Lunch is at noon. B: Facilities issues keys. Select evidence.'),
   dict(role='assistant',content='{"answerable":true,"selected":["B"]}'),
   dict(role='user',content='When does the shuttle leave and where does it stop? A: The library is open. B: The shuttle departs at 8am. C: Lunch is served at noon. D: It stops at East Gate.'),
   dict(role='assistant',content='{"answerable":true,"selected":["B","D"]}'),
   dict(role='user',content='Was my personal application approved? A: Applications are reviewed within ten days.'),
   dict(role='assistant',content='{"answerable":false,"selected":[]}'),
   dict(role='user',content=user)]''')
s=s.replace("  with torch.inference_mode():out=self.model.generate(**inputs,",'''  tokenizer=self.tokenizer;prompt_length=inputs['input_ids'].shape[1]
  class StopJSON(StoppingCriteria):
   def __call__(self,input_ids,scores,**kwargs):
    text=prefix+tokenizer.decode(input_ids[0,prompt_length:],skip_special_tokens=True)
    start=text.find('{')
    if start<0:return False
    try:json.JSONDecoder().raw_decode(text[start:]);return True
    except ValueError:return False
  with torch.inference_mode():out=self.model.generate(**inputs,num_logits_to_keep=1,stopping_criteria=StoppingCriteriaList([StopJSON()]),''')
p.write_text(s,encoding='utf-8')
p=Path('evaluate/local_reader_worker.py');s=p.read_text(encoding='utf-8').replace('reader-queue-v2','reader-queue-v3').replace('InstructionModel(small=True)','InstructionModel(small=False)');p.write_text(s,encoding='utf-8')
p=Path('evaluate/instruction_retrieval.py');s=p.read_text(encoding='utf-8-sig').replace('reader-queue-v2','reader-queue-v3').replace('reader-v2-','reader-v3-')
s=s.replace('Return ONLY JSON: {"answerable":true,"selected":["A","C"]}. If private/unsupported, return {"answerable":false,"selected":[]}. No explanation.', 'Return ONLY a JSON object with answerable (boolean) and selected (list of passage letters). If private/unsupported, answerable must be false and selected must be empty. Do not copy example IDs; use the actual relevant passages. No explanation.')
p.write_text(s,encoding='utf-8')
