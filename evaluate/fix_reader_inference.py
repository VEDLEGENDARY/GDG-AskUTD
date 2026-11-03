from pathlib import Path
p=Path('evaluate/instruction_model.py');s=p.read_text(encoding='utf-8')
s=s.replace("attn_implementation='sdpa'", "attn_implementation='eager'")
a=s.index("  print('Quantizing linear layers for CPU'")
b=s.index("  print(f'Instruction model ready",a)
s=s[:a]+"  self.model=model\n"+s[b:]
s=s.replace("self.tokenizer(text,return_tensors='pt')", "self.tokenizer(text,return_tensors='pt',add_special_tokens=False)")
p.write_text(s,encoding='utf-8')
p=Path('evaluate/local_reader_worker.py');s=p.read_text(encoding='utf-8-sig').replace("'runs/reader-queue'","'runs/reader-queue-v2'");p.write_text(s,encoding='utf-8')
