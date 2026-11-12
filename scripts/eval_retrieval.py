"""Evaluate the production retriever without model downloads or label leakage."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.retrieval import corpus_stats, retrieve
from evaluate import evaluate_chunks as ev


def evaluate(split: str) -> dict:
    """Grade one selected split and measure warmed request latency."""
    chunks = ev.read_chunks(ROOT / 'backend/data/chunks')
    questions_path = ROOT / 'evaluate/questions.json'
    questions = ev.read_questions(questions_path, chunks, split)
    corpus_stats()
    rows, latencies = [], []
    categories = defaultdict(list)
    for q in questions:
        start = time.perf_counter()
        result = retrieve(q['query'])
        elapsed = (time.perf_counter()-start)*1000
        latencies.append(elapsed)
        hits = [{**asdict(p), 'estimated_tokens': ev.cost(asdict(p))} for p in result.passages]
        row = {'id': q['id'], 'query': q['query'], 'reason': result.reason,
               'chunk_ids': [h['chunk_id'] for h in hits], 'latency_ms': elapsed,
               'metrics': ev.grade(q, hits)}
        rows.append(row)
        categories[q.get('category', 'uncategorized')].append(row)
    return {'split': split, 'questions_sha256': hashlib.sha256(questions_path.read_bytes()).hexdigest(),
            'summary': ev.summarize(rows),
            'categories': {name: {'questions': len(group), **ev.summarize(group)}
                           for name, group in sorted(categories.items())},
            'p50_ms': statistics.median(latencies),
            'p95_ms': sorted(latencies)[math.ceil(.95*len(latencies))-1], 'rows': rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=('dev', 'test'), required=True)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    if args.json and (args.json.resolve().is_relative_to(ROOT / 'backend/data')
                      or args.json.resolve() in {ROOT / 'evaluate/questions.json', ROOT / 'backend/retrieval_config.json'}):
        parser.error('output must not overwrite corpus, benchmark or runtime config')
    result = evaluate(args.split)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
