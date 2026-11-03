"""Ask a new question using frozen hybrid settings; does not fit on labels."""
from pathlib import Path
import argparse,json
from semantic_retrieval import Models,SemanticRetriever,ROOT
from lexical_retrieval_v2 import ImprovedRetriever
from hybrid_retrieval import Hybrid
from record_classifier import RecordDetector
from evaluate_chunks import read_chunks
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--query',required=True)
p.add_argument('--chunks',type=Path,default=ROOT.parent/'backend/data/chunks')
p.add_argument('--cache',type=Path,default=ROOT/'runs/semantic-hard/cache')
p.add_argument('--config',type=Path,default=ROOT/'hybrid.config.json')
p.add_argument('--detector',type=Path,default=ROOT/'hybrid.detector.json')
a=p.parse_args();models=Models();chunks=read_chunks(a.chunks)
s=SemanticRetriever(chunks,a.cache,models);r=Hybrid(s,ImprovedRetriever(chunks),ROOT/'runs/query-cache')
r.detector=RecordDetector.load(models,a.detector)
hits,reason=r.retrieve(a.query,json.loads(a.config.read_text()))
print(json.dumps(dict(query=a.query,abstention_reason=reason,retrieved=hits),indent=2,ensure_ascii=False))
