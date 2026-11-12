"""Mentee 5 benchmark: baseline vs optimized LexicalIndex, with parity, latency and memory.

Offline and dependency-free. Writes machine-readable JSON and prints a short summary.

    py scripts/mentee5_benchmark.py --json evaluate/runs/mentee-5/benchmark.json
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.retrieval_support.index import LexicalIndex  # noqa: E402
from evaluate import evaluate_chunks as ev  # noqa: E402
from evaluate.mentee5.baseline_index import BASELINE_COMMIT, BaselineLexicalIndex  # noqa: E402
from evaluate.mentee5.synthetic import make_corpus, make_queries, stress_queries  # noqa: E402

IMPLS = {'baseline': BaselineLexicalIndex, 'optimized': LexicalIndex}
CHUNKS_DIR = ROOT / 'backend/data/chunks'
TOLERANCE = 1e-9


def settings() -> ev.Settings:
    config = ev.read_json(ROOT / 'backend/retrieval_config.json')
    result = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    result.validate()
    return result


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q*len(ordered))-1)]


def summary(ms: list[float]) -> dict:
    return {'n': len(ms), 'p50_ms': statistics.median(ms), 'p95_ms': pct(ms, .95),
            'mean_ms': statistics.fmean(ms), 'max_ms': max(ms)}


def corpus_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(CHUNKS_DIR.rglob('*.json')):
        digest.update(path.relative_to(CHUNKS_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                             text=True, timeout=10).stdout.strip()
        if sha:
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    try:  # git not on PATH: read .git directly (loose refs only).
        head = (ROOT / '.git/HEAD').read_text().strip()
        return (ROOT / '.git' / head[5:]).read_text().strip() if head.startswith('ref: ') else head
    except OSError:
        return None


def parity(base, new, queries: list[str], top_k: int = 8) -> dict:
    mismatches, max_diff, compared = [], 0.0, 0
    for q in queries:
        left, right = base.search(q, top_k), new.search(q, top_k)
        if [h['chunk_id'] for h in left] != [h['chunk_id'] for h in right]:
            mismatches.append(q[:80])
        for a, b in zip(left, right):
            compared += 1
            max_diff = max(max_diff, abs(a['retrieval_score']-b['retrieval_score']))
            if a['estimated_tokens'] != b['estimated_tokens']:
                mismatches.append(q[:80])
    return {'queries': len(queries), 'top_k': top_k, 'hits_compared': compared,
            'id_mismatches': mismatches, 'max_abs_score_diff': max_diff,
            'passed': not mismatches and max_diff <= TOLERANCE}


def warm(indexes: dict, queries: list[str], runs: int, top_k: int = 5) -> dict:
    """One untimed warm-up pass, then `runs` timed passes; implementations alternate per pass."""
    samples = {name: [] for name in indexes}
    for index in indexes.values():
        for q in queries:
            index.search(q, top_k)
    names = list(indexes)
    for r in range(runs):
        for name in (names if r % 2 == 0 else names[::-1]):
            index = indexes[name]
            for q in queries:
                start = time.perf_counter()
                index.search(q, top_k)
                samples[name].append((time.perf_counter()-start)*1000)
    return {name: summary(ms) for name, ms in samples.items()}


def concurrency(index, queries: list[str], workers: int = 8, repeat: int = 5) -> dict:
    work = queries*repeat
    serial = [index.search(q, 5) for q in work]
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parallel = list(pool.map(lambda q: index.search(q, 5), work))
    elapsed = time.perf_counter()-start
    return {'workers': workers, 'calls': len(work), 'identical_to_serial': serial == parallel,
            'wall_ms': elapsed*1000}


def child(impl: str, mode: str, synthetic: int) -> dict:
    """Run in a fresh process: cold load timing or construction memory for one implementation."""
    cls, s = IMPLS[impl], settings()
    start = time.perf_counter()
    chunks = make_corpus(synthetic) if synthetic else ev.read_chunks(CHUNKS_DIR)
    read_ms = (time.perf_counter()-start)*1000
    gc.collect()
    if mode == 'memory':
        tracemalloc.start()
        index = cls(chunks, s)
        retained, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {'retained_bytes': retained, 'peak_bytes': peak, 'chunks': index.n}
    start = time.perf_counter()
    index = cls(chunks, s)
    build_ms = (time.perf_counter()-start)*1000
    start = time.perf_counter()
    index.search('How do I drop a class?', 5)
    first_ms = (time.perf_counter()-start)*1000
    return {'read_ms': read_ms, 'build_ms': build_ms, 'first_search_ms': first_ms}


def spawn(impl: str, mode: str, synthetic: int = 0) -> dict:
    out = subprocess.run([sys.executable, __file__, '--child', impl, mode, str(synthetic)],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def cold(processes: int, synthetic: int = 0) -> dict:
    result = {}
    for impl in IMPLS:
        runs = [spawn(impl, 'cold', synthetic) for _ in range(processes)]
        mem = spawn(impl, 'memory', synthetic)
        result[impl] = {
            'processes': processes,
            'build_ms_p50': statistics.median(r['build_ms'] for r in runs),
            'build_ms_max': max(r['build_ms'] for r in runs),
            'read_ms_p50': statistics.median(r['read_ms'] for r in runs),
            'first_search_ms_p50': statistics.median(r['first_search_ms'] for r in runs),
            'index_retained_bytes': mem['retained_bytes'], 'index_peak_bytes': mem['peak_bytes']}
    return result


def change(before: float, after: float) -> float:
    return (after-before)/before*100 if before else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runs', type=int, default=100, help='timed warm passes over the query set')
    parser.add_argument('--cold-processes', type=int, default=5)
    parser.add_argument('--synthetic-sizes', default='3000,12000', help='comma list, empty to skip')
    parser.add_argument('--synthetic-runs', type=int, default=10)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--json', type=Path, default=ROOT / 'evaluate/runs/mentee-5/benchmark.json')
    parser.add_argument('--child', nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(args.child[0], args.child[1], int(args.child[2]))))
        return
    if args.runs < 1 or args.cold_processes < 1:
        parser.error('--runs and --cold-processes must be positive')
    out = args.json.resolve()
    if out.is_relative_to(ROOT / 'backend') or out.suffix != '.json':
        parser.error('--json must be a .json path outside backend/')

    s = settings()
    chunks = ev.read_chunks(CHUNKS_DIR)
    dev = [q['query'] for q in ev.read_questions(ROOT / 'evaluate/questions.json', chunks, 'dev')]
    stress = stress_queries()
    indexes = {name: cls(chunks, s) for name, cls in IMPLS.items()}
    report = {
        'baseline_commit': BASELINE_COMMIT, 'commit': git_commit(),
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'machine': {'platform': platform.platform(), 'processor': platform.processor(),
                    'cpu_count': os.cpu_count()},
        'settings': asdict(s), 'corpus': {'sha256': corpus_hash(), 'chunks_loaded': len(chunks),
                                          'chunks_indexed': indexes['optimized'].n,
                                          'vocabulary': len(indexes['optimized'].df)},
        'query_set': {'dev': len(dev), 'stress': len(stress),
                      'questions_sha256': hashlib.sha256((ROOT / 'evaluate/questions.json').read_bytes()).hexdigest()},
        'tolerance': TOLERANCE,
    }
    print(f'Corpus {len(chunks)} chunks, {len(dev)} dev + {len(stress)} stress queries, Python {report["python"]}')
    report['parity'] = {'dev': parity(indexes['baseline'], indexes['optimized'], dev),
                        'stress': parity(indexes['baseline'], indexes['optimized'], stress)}
    report['warm_dev'] = warm(indexes, dev, args.runs)
    report['warm_stress'] = warm(indexes, stress, max(1, args.runs//10))
    report['concurrency'] = concurrency(indexes['optimized'], dev, args.threads)
    report['cold'] = cold(args.cold_processes)
    b, o = report['warm_dev']['baseline'], report['warm_dev']['optimized']
    cb, co = report['cold']['baseline'], report['cold']['optimized']
    report['real_corpus_change_pct'] = {
        'warm_p50': change(b['p50_ms'], o['p50_ms']), 'warm_p95': change(b['p95_ms'], o['p95_ms']),
        'cold_build_p50': change(cb['build_ms_p50'], co['build_ms_p50']),
        'index_retained_memory': change(cb['index_retained_bytes'], co['index_retained_bytes']),
        'index_peak_memory': change(cb['index_peak_bytes'], co['index_peak_bytes'])}

    report['synthetic'] = []
    for size in [int(x) for x in args.synthetic_sizes.split(',') if x.strip()]:
        syn_chunks, syn_queries = make_corpus(size), make_queries(size)
        syn = {name: cls(syn_chunks, s) for name, cls in IMPLS.items()}
        report['synthetic'].append({
            'label': 'SYNTHETIC (not real corpus)', 'chunks': size, 'queries': len(syn_queries),
            'parity': parity(syn['baseline'], syn['optimized'], syn_queries),
            'warm': warm(syn, syn_queries, args.synthetic_runs),
            'cold': cold(max(1, args.cold_processes//2), size)})
        del syn

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

    ok = all(p['passed'] for p in report['parity'].values()) and all(x['parity']['passed'] for x in report['synthetic'])
    ch = report['real_corpus_change_pct']
    print(f'Parity: {"PASS" if ok else "FAIL"} (dev max diff {report["parity"]["dev"]["max_abs_score_diff"]:.1e})')
    print(f'Warm dev  p50 {b["p50_ms"]:.2f} -> {o["p50_ms"]:.2f} ms  p95 {b["p95_ms"]:.2f} -> {o["p95_ms"]:.2f} ms'
          f'  ({ch["warm_p95"]:+.1f}% p95, {args.runs} runs)')
    print(f'Cold build p50 {cb["build_ms_p50"]:.0f} -> {co["build_ms_p50"]:.0f} ms ({ch["cold_build_p50"]:+.1f}%)'
          f'  index memory {cb["index_retained_bytes"]/1e6:.1f} -> {co["index_retained_bytes"]/1e6:.1f} MB'
          f' ({ch["index_retained_memory"]:+.1f}%)')
    print(f'Concurrency: {report["concurrency"]["calls"]} calls on {args.threads} threads, '
          f'identical={report["concurrency"]["identical_to_serial"]}')
    for x in report['synthetic']:
        w = x['warm']
        print(f'SYNTHETIC {x["chunks"]} chunks: p95 {w["baseline"]["p95_ms"]:.2f} -> {w["optimized"]["p95_ms"]:.2f} ms,'
              f' build {x["cold"]["baseline"]["build_ms_p50"]:.0f} -> {x["cold"]["optimized"]["build_ms_p50"]:.0f} ms,'
              f' parity {"PASS" if x["parity"]["passed"] else "FAIL"}')
    print(f'JSON: {out}')
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
