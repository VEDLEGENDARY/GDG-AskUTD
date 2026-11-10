#!/usr/bin/env python3
"""Mentee 1 retrieval evaluation harness: regression fixtures, adapters, reports.

Subcommands (run from the repository root):

  validate  Check evaluate/mentee1/cases.json against the corpus (IDs, quotes, labels).
  run       Evaluate one adapter on fixed suites and write JSON and Markdown reports.
  compare   Compare two run reports made under identical inputs, with per-query deltas.
  peers     Read other mentees' case files (read-only) and report overlaps.

The harness never passes labels to retrieval: an adapter receives only
(query, top_k, history). Rank scores are recorded as raw ranking scores and are
never interpreted as probabilities. See evaluate/mentee1/README.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import platform
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.types import RetrievalResult, Turn  # noqa: E402
from evaluate import evaluate_chunks as ev  # noqa: E402

TOOL_VERSION = 1
SCHEMA_VERSION = 1
CASES_PATH = ROOT / 'evaluate' / 'mentee1' / 'cases.json'
QUESTIONS_PATH = ROOT / 'evaluate' / 'questions.json'
CONFIG_PATH = ROOT / 'backend' / 'retrieval_config.json'
CATEGORIES = ('direct_lookup', 'paraphrase', 'abbreviation', 'population_contrast',
              'time_contrast', 'compound', 'near_miss', 'unanswerable', 'follow_up')
MIN_CASES, MIN_UNANSWERABLE = 30, 8
MIN_QUOTE_WORDS = 3
CASE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{2,79}$')
CASE_KEYS = {'id', 'category', 'query', 'history', 'unanswerable', 'evidence', 'requirement',
             'distractors', 'unanswerable_reason', 'nearest_related', 'absence_checks',
             'unsupported_parts', 'notes'}
GROUP_KEYS = {'id', 'support', 'not_equivalent', 'note'}
PEER_GLOB = 'evaluate/mentee[2-5]/**/*.json'
QUALITY_KEYS = ('evidence_recall', 'complete_evidence', 'reciprocal_rank', 'context_precision')


class HarnessError(ValueError):
    """Invalid input that should stop the command with a readable message."""


# ---------------------------------------------------------------- inputs

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(obj) -> str:
    """Same canonical JSON fingerprint evaluate_chunks.py uses for corpus_sha256."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode())


def load_config(path: Path = CONFIG_PATH) -> tuple[dict, ev.Settings]:
    config = ev.read_json(path)
    if not isinstance(config, dict):
        raise HarnessError(f'{path}: config must be a JSON object')
    names = [f for f in ev.Settings.__dataclass_fields__]
    missing = [n for n in names if n not in config]
    if missing:
        raise HarnessError(f'{path}: missing settings {missing}')
    settings = ev.Settings(**{n: config[n] for n in names})
    settings.validate()
    return config, settings


class Corpus:
    """Chunk lookup plus normalized text for quote verification."""

    def __init__(self, chunks: list[dict], settings: ev.Settings):
        self.chunks = chunks
        self.by_id = {c['chunk_id']: c for c in chunks}
        self.padded = {c['chunk_id']: ' ' + ev.normalize(c['text']) + ' ' for c in chunks}
        self.eligible = {c['chunk_id'] for c in chunks
                         if settings.min_chunk_words <= len(c['text'].split()) <= settings.max_chunk_words}
        self.sha256 = fingerprint(chunks)

    def contains(self, chunk_id: str, quote: str) -> bool:
        return (' ' + ev.normalize(quote) + ' ') in self.padded.get(chunk_id, '')

    def matching(self, quote: str) -> list[str]:
        needle = ' ' + ev.normalize(quote) + ' '
        return sorted(cid for cid, text in self.padded.items() if needle in text)


def load_corpus(config: dict, settings: ev.Settings, root: Path = ROOT) -> Corpus:
    return Corpus(ev.read_chunks(root / config['chunks_path']), settings)


# ------------------------------------------------------------ validation

def _str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_refs(where: str, items, corpus: Corpus, errors: list[str], label: str) -> list[str]:
    """Validate a list of {chunk_id, reason} references and return their IDs."""
    ids = []
    if not isinstance(items, list):
        errors.append(f'{where}: {label} must be a list')
        return ids
    for item in items:
        if not isinstance(item, dict) or set(item) - {'chunk_id', 'reason'} or not _str(item.get('chunk_id')) \
                or not _str(item.get('reason')):
            errors.append(f'{where}: each {label} entry needs chunk_id and reason strings only')
            continue
        if item['chunk_id'] not in corpus.by_id:
            errors.append(f"{where}: {label} chunk ID {item['chunk_id']!r} is missing from the corpus")
        ids.append(item['chunk_id'])
    if len(ids) != len(set(ids)):
        errors.append(f'{where}: duplicate {label} chunk IDs')
    return ids


def _check_history(where: str, history, errors: list[str]) -> None:
    if not isinstance(history, list) or not history:
        errors.append(f'{where}: history must be a nonempty list of turns')
        return
    for turn in history:
        if not isinstance(turn, dict) or set(turn) != {'role', 'content'} \
                or turn.get('role') not in ('user', 'assistant') or not _str(turn.get('content')):
            errors.append(f'{where}: each history turn needs role user/assistant and nonempty content')
            return
    if not any(t['role'] == 'user' for t in history):
        errors.append(f'{where}: history needs at least one user turn')


def validate_case(case, corpus: Corpus) -> list[str]:
    """Return label errors for one case. An empty list means the labels verify."""
    if not isinstance(case, dict):
        return ['case must be an object']
    where = case.get('id') if _str(case.get('id')) else '<missing id>'
    errors: list[str] = []
    unknown = set(case) - CASE_KEYS
    if unknown:
        errors.append(f'{where}: unknown keys {sorted(unknown)}')
    if not _str(case.get('id')) or not CASE_ID.match(case['id']):
        errors.append(f'{where}: id must match {CASE_ID.pattern}')
    if case.get('category') not in CATEGORIES:
        errors.append(f'{where}: category must be one of {list(CATEGORIES)}')
    if not _str(case.get('query')) or not ev.tokens(case['query']):
        errors.append(f'{where}: query must contain searchable words')
    if type(case.get('unanswerable')) is not bool:
        errors.append(f'{where}: unanswerable must be a boolean')
    if case.get('notes') is not None and not _str(case.get('notes')):
        errors.append(f'{where}: notes must be a nonempty string when present')
    if case.get('category') == 'follow_up':
        _check_history(where, case.get('history'), errors)
    elif 'history' in case:
        errors.append(f'{where}: only follow_up cases store history')
    if case.get('category') == 'unanswerable' and case.get('unanswerable') is False:
        errors.append(f'{where}: unanswerable category requires unanswerable=true')
    evidence = case.get('evidence')
    if not isinstance(evidence, list):
        errors.append(f'{where}: evidence must be a list')
        return errors
    support_ids: set[str] = set()
    if case.get('unanswerable') is True:
        if evidence:
            errors.append(f'{where}: unanswerable cases must have empty evidence')
        if not _str(case.get('unanswerable_reason')) or len(case.get('unanswerable_reason', '')) < 40:
            errors.append(f'{where}: unanswerable_reason must explain why the corpus cannot answer')
        checks = case.get('absence_checks')
        if not isinstance(checks, list) or not checks or not all(_str(c) for c in checks):
            errors.append(f'{where}: absence_checks must list the searches and documents reviewed')
        _check_refs(where, case.get('nearest_related', None), corpus, errors, 'nearest_related')
        if 'requirement' in case:
            errors.append(f'{where}: requirement applies to answerable cases only')
    elif case.get('unanswerable') is False:
        if not evidence:
            errors.append(f'{where}: answerable cases require at least one evidence group')
        for key in ('unanswerable_reason', 'nearest_related', 'absence_checks'):
            if key in case:
                errors.append(f'{where}: {key} applies to unanswerable cases only')
        if not _str(case.get('requirement')):
            errors.append(f'{where}: requirement must explain why each evidence group is required')
        group_ids = set()
        for group in evidence:
            gwhere = f"{where}/{group.get('id', '?') if isinstance(group, dict) else '?'}"
            if not isinstance(group, dict) or set(group) - GROUP_KEYS:
                errors.append(f'{gwhere}: group keys must be within {sorted(GROUP_KEYS)}')
                continue
            if not _str(group.get('id')) or group['id'] in group_ids:
                errors.append(f'{gwhere}: group id must be a unique nonempty string')
            group_ids.add(group.get('id'))
            support = group.get('support')
            if not isinstance(support, list) or not support:
                errors.append(f'{gwhere}: support must be a nonempty list')
                continue
            listed = []
            for item in support:
                if not isinstance(item, dict) or set(item) != {'chunk_id', 'quote'} \
                        or not _str(item.get('chunk_id')) or not _str(item.get('quote')):
                    errors.append(f'{gwhere}: each support entry needs exactly chunk_id and quote strings')
                    continue
                cid, quote = item['chunk_id'], item['quote']
                listed.append(cid)
                if cid not in corpus.by_id:
                    errors.append(f'{gwhere}: chunk ID {cid!r} is missing from the corpus')
                    continue
                if len(ev.normalize(quote).split()) < MIN_QUOTE_WORDS:
                    errors.append(f'{gwhere}: quote for {cid} needs at least {MIN_QUOTE_WORDS} words')
                if not corpus.contains(cid, quote):
                    errors.append(f'{gwhere}: quote does not occur in {cid}: {quote!r}')
            if len(listed) != len(set(listed)):
                errors.append(f'{gwhere}: duplicate support chunk IDs')
            rejected = _check_refs(gwhere, group.get('not_equivalent', []), corpus, errors, 'not_equivalent')
            if set(rejected) & set(listed):
                errors.append(f'{gwhere}: a chunk cannot be both support and not_equivalent')
            for item in support:
                if isinstance(item, dict) and _str(item.get('quote')) and item.get('chunk_id') in corpus.by_id:
                    extra = [c for c in corpus.matching(item['quote']) if c not in listed and c not in rejected]
                    if extra:
                        errors.append(f'{gwhere}: quote {item["quote"]!r} also occurs in unlisted chunks {extra}; '
                                      'add them as support or as not_equivalent with a reason')
            support_ids.update(listed)
        if group_ids and len(group_ids) > 1 and 'all' not in case.get('requirement', '').lower():
            errors.append(f'{where}: multi-group requirement text must state that all groups are required')
    distractor_ids = _check_refs(where, case.get('distractors', []), corpus, errors, 'distractors')
    if set(distractor_ids) & support_ids:
        errors.append(f'{where}: distractors overlap required evidence')
    if 'unsupported_parts' in case and (not isinstance(case['unsupported_parts'], list)
                                        or not all(_str(p) for p in case['unsupported_parts'])):
        errors.append(f'{where}: unsupported_parts must be a list of strings')
    return errors


def history_key(case: dict) -> tuple:
    return tuple((t['role'], ev.normalize(t['content'])) for t in case.get('history') or []
                 if isinstance(t, dict) and isinstance(t.get('content'), str))


def validate_cases(data, corpus: Corpus, require_coverage: bool = True) -> tuple[list[dict], list[str]]:
    """Validate a cases document. Returns (cases, errors)."""
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA_VERSION \
            or not isinstance(data.get('cases'), list) or not data['cases']:
        return [], [f'cases file needs schema_version {SCHEMA_VERSION} and a nonempty cases list']
    errors: list[str] = []
    seen_ids, seen_queries = set(), set()
    for case in data['cases']:
        errors.extend(validate_case(case, corpus))
        if isinstance(case, dict):
            if case.get('id') in seen_ids:
                errors.append(f"{case.get('id')}: duplicate case id")
            seen_ids.add(case.get('id'))
            if isinstance(case.get('query'), str):
                key = (ev.normalize(case['query']), history_key(case))
                if key in seen_queries:
                    errors.append(f"{case.get('id')}: duplicate query and history")
                seen_queries.add(key)
    cases = [c for c in data['cases'] if isinstance(c, dict)]
    if require_coverage:
        errors.extend(coverage_problems(cases))
    return cases, errors


def coverage_problems(cases: list[dict]) -> list[str]:
    problems = []
    if len(cases) < MIN_CASES:
        problems.append(f'need at least {MIN_CASES} cases, found {len(cases)}')
    unanswerable = sum(c.get('unanswerable') is True for c in cases)
    if unanswerable < MIN_UNANSWERABLE:
        problems.append(f'need at least {MIN_UNANSWERABLE} unanswerable cases, found {unanswerable}')
    present = {c.get('category') for c in cases}
    missing = [c for c in CATEGORIES if c not in present]
    if missing:
        problems.append(f'missing categories: {missing}')
    return problems


def oracle_feasible(case: dict, corpus: Corpus, settings: ev.Settings, top_k: int) -> bool:
    """Could some selection of indexable chunks cover every group within production limits?"""
    groups = [[s['chunk_id'] for s in g['support'] if s['chunk_id'] in corpus.eligible]
              for g in case.get('evidence', [])]
    if not groups:
        return True
    if any(not g for g in groups):
        return False
    options = sorted({cid for g in groups for cid in g})

    def search(index, chosen):
        if index == len(groups):
            docs = Counter(corpus.by_id[c]['doc_id'] for c in chosen)
            return (len(chosen) <= top_k and max(docs.values()) <= settings.max_per_document
                    and sum(ev.cost(corpus.by_id[c]) for c in chosen) <= settings.context_budget)
        if any(c in chosen for c in groups[index]):
            return search(index + 1, chosen)
        return any(search(index + 1, chosen | {c}) for c in groups[index] if c in options)

    return search(0, frozenset())


def load_cases(path: Path, corpus: Corpus, require_coverage: bool = True) -> list[dict]:
    try:
        data = ev.read_json(path)
    except (OSError, ValueError) as exc:
        raise HarnessError(f'{path}: {exc}') from exc
    cases, errors = validate_cases(data, corpus, require_coverage)
    if errors:
        raise HarnessError(f'{path}: {len(errors)} label error(s):\n  ' + '\n  '.join(errors))
    return cases


# ---------------------------------------------------------------- adapters

class Adapter:
    """A retrieval callable plus optional warmup. Receives only query, top_k, history."""

    def __init__(self, name: str, fn, warmup=None, description: str = ''):
        self.name, self.fn, self.warmup, self.description = name, fn, warmup, description

    def __call__(self, query: str, top_k: int, history):
        return self.fn(query, top_k, history)


def _production(reject_rules: bool = True) -> Adapter:
    from backend.app import retrieval
    from backend.app.retrieval_support.query import rewrite

    def warmup():
        retrieval._load.cache_clear()
        retrieval.corpus_stats()

    if reject_rules:
        return Adapter('production', lambda q, k, h: retrieval.retrieve(q, top_k=k, history=h), warmup,
                       'backend.app.retrieval.retrieve with production config')

    def no_reject(query, top_k, history):
        # Ablation only: same rewrite and index, but no abstention rules after search.
        index, _, urls, _ = retrieval._load()
        hits = index.search(rewrite(query.strip()[:2000], history), top_k)
        return [{**h, 'score': h['retrieval_score'], 'source_url': urls.get(h['doc_id'])} for h in hits]

    return Adapter('production-no-reject', no_reject, warmup,
                   'ablation: production rewrite and index without reject() abstention rules')


BUILTIN_ADAPTERS = {
    'production': lambda: _production(True),
    'production-no-reject': lambda: _production(False),
    'always-abstain': lambda: Adapter('always-abstain', lambda q, k, h: RetrievalResult(abstain=True, reason='sanity'),
                                      None, 'sanity check: abstains on every query'),
}


def load_adapter(spec: str) -> Adapter:
    """Resolve a built-in name, module.path:callable, or path/to/file.py:callable."""
    if spec in BUILTIN_ADAPTERS:
        return BUILTIN_ADAPTERS[spec]()
    target, sep, attr = spec.rpartition(':')
    if not sep or not target or not attr:
        raise HarnessError(f'adapter {spec!r}: use a built-in {sorted(BUILTIN_ADAPTERS)} or module:callable')
    if target.endswith('.py'):
        path = Path(target).resolve()
        loader = importlib.util.spec_from_file_location(f'mentee1_adapter_{sha256_bytes(str(path).encode())[:12]}', path)
        if loader is None or loader.loader is None:
            raise HarnessError(f'adapter {spec!r}: cannot load {path}')
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise HarnessError(f'adapter {spec!r}: {attr} is not callable')
    return Adapter(spec, fn, getattr(fn, 'warmup', None), (getattr(fn, '__doc__', '') or '').strip()[:200])


def normalize_result(result) -> tuple[bool, str | None, list[dict], list[str]]:
    """Convert RetrievalResult or a list of passages/dicts to (abstain, reason, hits, problems)."""
    problems = []
    if hasattr(result, 'passages') and hasattr(result, 'abstain'):
        passages, abstain, reason = list(result.passages or []), bool(result.abstain), result.reason
        if abstain and passages:
            problems.append('abstain_with_passages')
        if not abstain and not passages:
            problems.append('empty_without_abstain')
    elif isinstance(result, list):
        passages, abstain, reason = result, not result, None if result else 'no passages'
    else:
        raise TypeError(f'adapter returned {type(result).__name__}, expected RetrievalResult or list')
    hits = []
    for passage in passages:
        row = asdict(passage) if is_dataclass(passage) else dict(passage) if isinstance(passage, dict) else None
        if row is None or not _str(row.get('chunk_id')):
            problems.append('malformed_passage')
            continue
        score = row.get('score', row.get('retrieval_score'))
        hit = {'chunk_id': row['chunk_id'], 'doc_id': row.get('doc_id') or '', 'text': row.get('text') or '',
               'source_title': row.get('source_title') or '', 'section_heading': row.get('section_heading') or '',
               'score': score, 'source_url': row.get('source_url')}
        hit['estimated_tokens'] = ev.cost(hit)
        hits.append(hit)
    return abstain or not hits, reason, hits, problems


def integrity(hits: list[dict], corpus: Corpus, settings: ev.Settings, top_k: int,
              urls: dict[str, str]) -> list[str]:
    """Contract violations that must never be traded for a better metric."""
    out = []
    ids = [h['chunk_id'] for h in hits]
    if len(hits) > top_k:
        out.append('top_k_exceeded')
    if len(ids) != len(set(ids)):
        out.append('duplicate_chunk_id')
    if sum(h['estimated_tokens'] for h in hits) > settings.context_budget:
        out.append('over_context_budget')
    if any(n > settings.max_per_document for n in Counter(h['doc_id'] for h in hits).values()):
        out.append('document_cap_exceeded')
    for h in hits:
        row = corpus.by_id.get(h['chunk_id'])
        if row is None:
            out.append('unknown_chunk_id')
            continue
        if h['text'] != row['text'] or h['doc_id'] != row['doc_id']:
            out.append('passage_text_or_doc_mismatch')
        if not isinstance(h['score'], (int, float)) or isinstance(h['score'], bool) \
                or not math.isfinite(h['score']) or h['score'] <= 0:
            out.append('non_positive_or_invalid_score')
        url, expected = h['source_url'], urls.get(h['doc_id'])
        if url is not None and (not isinstance(url, str) or not url.startswith(('https://', 'http://'))):
            out.append('unsafe_url')
        elif expected and url != expected:
            out.append('missing_or_mismatched_url')
        elif url is not None and not expected:
            out.append('url_not_in_registry')
    return sorted(set(out))


# ------------------------------------------------------------------ grading

def coverage_metrics(covered: list[bool], relevant: list[bool], unanswerable: bool, hits: list[dict]) -> dict:
    """Exactly the expressions in evaluate_chunks.grade(), given coverage flags.

    covered[i]: evidence group i is supported by some hit. relevant[j]: hit j supports
    some group. Only how support is decided differs (chunk ID labels instead of phrases);
    test_mentee1_eval.py checks parity against ev.grade.
    """
    return {
        'evidence_recall': sum(covered) / len(covered) if covered else None,
        'complete_evidence': int(all(covered)) if covered else None,
        'reciprocal_rank': next((1 / (i + 1) for i, ok in enumerate(relevant) if ok), 0) if covered else None,
        'context_precision': sum(relevant) / len(hits) if hits and covered else (0 if covered else None),
        'abstention_correct': int(not hits) if unanswerable else None,
        'estimated_tokens': sum(h['estimated_tokens'] for h in hits),
    }


def grade_case(case: dict, hits: list[dict]) -> dict:
    groups = [{s['chunk_id'] for s in g['support']} for g in case.get('evidence', [])]
    support = set().union(*groups) if groups else set()
    ids = [h['chunk_id'] for h in hits]
    covered = [any(i in g for i in ids) for g in groups]
    relevant = [i in support for i in ids]
    metrics = coverage_metrics(covered, relevant, case['unanswerable'], hits)
    distractors = {d['chunk_id'] for d in case.get('distractors', [])}
    related = {d['chunk_id'] for d in case.get('nearest_related', [])}
    first_evidence = next((n for n, ok in enumerate(relevant, 1) if ok), None)
    first_distractor = next((n for n, i in enumerate(ids, 1) if i in distractors), None)
    return {**metrics, 'evidence_covered': covered,
            'distractor_hits': sum(i in distractors for i in ids),
            'distractor_before_evidence': int(first_distractor is not None
                                              and (first_evidence is None or first_distractor < first_evidence)),
            'nearest_related_hits': sum(i in related for i in ids),
            'first_evidence_rank': first_evidence}


def grade_question(question: dict, hits: list[dict]) -> dict:
    """Existing benchmark questions: unchanged evaluate_chunks.grade()."""
    covered = [any(ev.supports(h, e) for h in hits) for e in question['evidence']]
    return {**ev.grade(question, hits), 'evidence_covered': covered, 'distractor_hits': 0,
            'distractor_before_evidence': 0, 'nearest_related_hits': 0,
            'first_evidence_rank': next((n for n, h in enumerate(hits, 1)
                                         if any(ev.supports(h, e) for e in question['evidence'])), None)}


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict]) -> dict:
    """Quality on answerable cases, answerability, distractors, context size and integrity."""
    answerable = [r for r in rows if not r['unanswerable']]
    unanswerable = [r for r in rows if r['unanswerable']]
    quality = {k: _mean(r['metrics'][k] for r in answerable) for k in QUALITY_KEYS}
    refused = sum(r['abstained'] for r in answerable)
    accepted = sum(not r['abstained'] for r in unanswerable)
    tokens = [r['metrics']['estimated_tokens'] for r in rows if not r['abstained']]
    violations = Counter(v for r in rows for v in r['integrity'])
    return {
        'cases': len(rows),
        'quality_answerable': quality,
        'answerability': {
            'answerable': len(answerable), 'answerable_abstained': refused,
            'false_refusal_rate': refused / len(answerable) if answerable else None,
            'unanswerable': len(unanswerable), 'unanswerable_accepted': accepted,
            'false_acceptance_rate': accepted / len(unanswerable) if unanswerable else None,
        },
        'distractors': {
            'cases_with_distractor_hits': sum(r['metrics']['distractor_hits'] > 0 for r in rows),
            'distractor_before_evidence': sum(r['metrics']['distractor_before_evidence'] for r in rows),
            'unanswerable_with_nearest_related_hits': sum(r['metrics']['nearest_related_hits'] > 0
                                                          for r in unanswerable),
        },
        'context': {'mean_estimated_tokens': _mean(tokens), 'max_estimated_tokens': max(tokens, default=0),
                    'mean_passages': _mean([len(r['ranked']) for r in rows if not r['abstained']])},
        'integrity': {'cases_with_violations': sum(bool(r['integrity']) for r in rows),
                      'violations': dict(sorted(violations.items()))},
        'flags': {'all_abstain': bool(rows) and all(r['abstained'] for r in rows),
                  'never_abstains_on_unanswerable': bool(unanswerable) and accepted == len(unanswerable)},
        'reference_leaderboard': ev.summarize(rows)['leaderboard_score'],
    }


def nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


# ---------------------------------------------------------------------- run

def git_state() -> dict:
    def git(*args):
        try:
            return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = git('status', '--porcelain', '--untracked-files=no')
    return {'commit': git('rev-parse', 'HEAD'), 'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'tracked_changes': None if status is None else bool(status)}


def environment() -> dict:
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'platform': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor(),
            **git_state()}


def build_suites(names: list[str], cases_path: Path, corpus: Corpus, allow_test: bool) -> dict:
    """Load each suite's items in file order with input hashes. Labels stay in the harness."""
    suites = {}
    for name in names:
        if name == 'mentee1':
            items = [{'suite': name, 'id': c['id'], 'category': c['category'], 'query': c['query'],
                      'history': c.get('history'), 'unanswerable': c['unanswerable'], 'label': c}
                     for c in load_cases(cases_path, corpus)]
            suites[name] = {'path': str(cases_path), 'sha256': sha256_bytes(cases_path.read_bytes()), 'items': items}
        elif name in ('dev', 'test'):
            if name == 'test' and not allow_test:
                raise HarnessError('the test split is a used regression set; pass --allow-test-split and do not tune on it')
            questions = ev.read_questions(QUESTIONS_PATH, corpus.chunks, split=name)
            items = [{'suite': name, 'id': q['id'], 'category': q['category'], 'query': q['query'],
                      'history': None, 'unanswerable': q['unanswerable'], 'label': q} for q in questions]
            suites[name] = {'path': str(QUESTIONS_PATH), 'sha256': sha256_bytes(QUESTIONS_PATH.read_bytes()),
                            'items': items}
        else:
            raise HarnessError(f'unknown suite {name!r}')
    return suites


def run(adapter: Adapter, suites: dict, corpus: Corpus, settings: ev.Settings, urls: dict[str, str],
        top_k: int = 5, repeat: int = 3, order: str = 'id') -> dict:
    """Evaluate in a fixed order. Ranking comes from repetition 1; all repetitions are timed."""
    if type(top_k) is not int or not 1 <= top_k <= 8:
        raise HarnessError('top_k must be an integer from 1 through 8')
    if type(repeat) is not int or repeat < 1:
        raise HarnessError('repeat must be a positive integer')
    items = [item for suite in suites.values() for item in suite['items']]
    if order == 'id':
        items.sort(key=lambda item: (item['suite'], item['id']))
    elif order != 'file':
        raise HarnessError('order must be id or file')
    cold_ms, cold_source = None, None
    if adapter.warmup is not None:
        start = time.perf_counter()
        adapter.warmup()
        cold_ms, cold_source = (time.perf_counter() - start) * 1000, 'adapter warmup'
    elif items:
        first = items[0]
        start = time.perf_counter()
        _call(adapter, first, top_k)
        cold_ms, cold_source = (time.perf_counter() - start) * 1000, 'first query (untimed afterwards)'
    rows = {}
    latencies = []
    for rep in range(repeat):
        for item in items:
            start = time.perf_counter()
            outcome = _call(adapter, item, top_k)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            key = (item['suite'], item['id'])
            if rep == 0:
                rows[key] = _row(item, outcome, corpus, settings, top_k, urls)
                rows[key]['latency_ms'] = []
            elif [h['chunk_id'] for h in outcome[2]] != rows[key]['ranked'] and 'nondeterministic_ranking' \
                    not in rows[key]['integrity']:
                rows[key]['integrity'] = sorted(rows[key]['integrity'] + ['nondeterministic_ranking'])
            rows[key]['latency_ms'].append(elapsed)
    ordered_rows = [rows[(item['suite'], item['id'])] for item in items]
    by_suite = {}
    for name in suites:
        suite_rows = [r for r in ordered_rows if r['suite'] == name]
        by_suite[name] = {'summary': summarize(suite_rows),
                          'by_category': {cat: summarize([r for r in suite_rows if r['category'] == cat])
                                          for cat in sorted({r['category'] for r in suite_rows})}}
    return {
        'tool': 'mentee1_eval', 'tool_version': TOOL_VERSION,
        'created_unix': int(time.time()), 'environment': environment(),
        'adapter': {'name': adapter.name, 'description': adapter.description},
        'inputs': {'corpus_sha256': corpus.sha256, 'chunks': len(corpus.chunks),
                   'documents': len({c['doc_id'] for c in corpus.chunks}),
                   'config_sha256': sha256_bytes(CONFIG_PATH.read_bytes()),
                   'suites': {n: {'path': str(Path(s['path']).relative_to(ROOT)) if Path(s['path']).is_relative_to(ROOT)
                                  else s['path'], 'sha256': s['sha256'], 'items': len(s['items'])}
                              for n, s in suites.items()}},
        'settings': {'top_k': top_k, 'repeat': repeat, 'order': order, 'context_budget': settings.context_budget,
                     'max_per_document': settings.max_per_document},
        'timing': {'cold_load_ms': cold_ms, 'cold_source': cold_source,
                   'warm_p50_ms': statistics.median(latencies) if latencies else None,
                   'warm_p95_ms': nearest_rank(latencies, .95), 'warm_max_ms': max(latencies, default=None),
                   'timed_calls': len(latencies)},
        'score_note': 'scores are ranking scores from the adapter, not probabilities or confidence',
        'suites': by_suite,
        'rows': ordered_rows,
    }


def _call(adapter: Adapter, item: dict, top_k: int):
    history = [Turn(t['role'], t['content']) for t in item['history']] if item['history'] else None
    try:
        return normalize_result(adapter(item['query'], top_k, history))
    except Exception as exc:  # noqa: BLE001 - a failing adapter is a reportable outcome
        return True, f'adapter error: {type(exc).__name__}: {exc}', [], ['adapter_error']


def _row(item, outcome, corpus, settings, top_k, urls) -> dict:
    abstained, reason, hits, problems = outcome
    if item['suite'] == 'mentee1':
        metrics = grade_case(item['label'], hits)
    else:
        metrics = grade_question(item['label'], hits)
    return {'suite': item['suite'], 'id': item['id'], 'category': item['category'], 'query': item['query'],
            'has_history': bool(item['history']), 'unanswerable': item['unanswerable'],
            'abstained': abstained, 'reason': reason,
            'ranked': [h['chunk_id'] for h in hits], 'scores': [h['score'] for h in hits],
            'source_urls': [h['source_url'] for h in hits],
            'metrics': metrics, 'integrity': sorted(set(problems + integrity(hits, corpus, settings, top_k, urls)))}


# ------------------------------------------------------------------ compare

def compare(base: dict, cand: dict, allow_mismatch: bool = False) -> dict:
    """Per-query and aggregate deltas between two reports built from identical inputs."""
    problems = []
    if base['inputs']['corpus_sha256'] != cand['inputs']['corpus_sha256']:
        problems.append('corpus differs')
    if {n: s['sha256'] for n, s in base['inputs']['suites'].items()} != \
            {n: s['sha256'] for n, s in cand['inputs']['suites'].items()}:
        problems.append('suites or labels differ')
    if base['settings']['top_k'] != cand['settings']['top_k']:
        problems.append('top_k differs')
    if problems and not allow_mismatch:
        raise HarnessError('reports are not comparable: ' + ', '.join(problems)
                           + ' (rerun both under identical inputs, or pass --allow-mismatch)')
    notes = list(problems)
    if base['inputs']['config_sha256'] != cand['inputs']['config_sha256']:
        notes.append('retrieval config file differs between runs')
    if base['environment'].get('machine') != cand['environment'].get('machine') \
            or base['environment'].get('python') != cand['environment'].get('python'):
        notes.append('machine or Python differs; latency deltas are not comparable')
    base_rows = {(r['suite'], r['id']): r for r in base['rows']}
    cand_rows = {(r['suite'], r['id']): r for r in cand['rows']}
    per_query = []
    for key in sorted(base_rows.keys() & cand_rows.keys()):
        b, c = base_rows[key], cand_rows[key]
        delta = {k: (None if b['metrics'][k] is None or c['metrics'][k] is None
                     else c['metrics'][k] - b['metrics'][k]) for k in QUALITY_KEYS}
        regressions, improvements = [], []
        for k in ('complete_evidence', 'evidence_recall', 'reciprocal_rank', 'context_precision'):
            if delta[k] is not None and delta[k] < -1e-12:
                regressions.append(f'{k} down')
            elif delta[k] is not None and delta[k] > 1e-12:
                improvements.append(f'{k} up')
        if not b['unanswerable'] and c['abstained'] and not b['abstained']:
            regressions.append('newly refuses answerable')
        if not b['unanswerable'] and b['abstained'] and not c['abstained']:
            improvements.append('now answers')
        if b['unanswerable'] and not c['abstained'] and b['abstained']:
            regressions.append('newly accepts unanswerable')
        if b['unanswerable'] and c['abstained'] and not b['abstained']:
            improvements.append('now abstains')
        if c['metrics']['distractor_before_evidence'] > b['metrics']['distractor_before_evidence']:
            regressions.append('distractor now outranks evidence')
        new_violations = sorted(set(c['integrity']) - set(b['integrity']))
        if new_violations:
            regressions.append('new integrity violations: ' + ', '.join(new_violations))
        per_query.append({'suite': key[0], 'id': key[1], 'category': b['category'], 'unanswerable': b['unanswerable'],
                          'delta': delta, 'base_abstained': b['abstained'], 'cand_abstained': c['abstained'],
                          'same_ranking': b['ranked'] == c['ranked'], 'base_ranked': b['ranked'],
                          'cand_ranked': c['ranked'], 'regressions': regressions, 'improvements': improvements})
    aggregate = {}
    for suite in sorted(set(base['suites']) & set(cand['suites'])):
        aggregate[suite] = {'overall': _summary_delta(base['suites'][suite]['summary'], cand['suites'][suite]['summary']),
                            'by_category': {cat: _summary_delta(base['suites'][suite]['by_category'][cat],
                                                                cand['suites'][suite]['by_category'][cat])
                                            for cat in sorted(set(base['suites'][suite]['by_category'])
                                                              & set(cand['suites'][suite]['by_category']))}}
    timing = {k: (None if base['timing'][k] is None or cand['timing'][k] is None
                  else cand['timing'][k] - base['timing'][k]) for k in ('cold_load_ms', 'warm_p50_ms', 'warm_p95_ms')}
    return {'base': base['adapter']['name'], 'candidate': cand['adapter']['name'], 'notes': notes,
            'aggregate': aggregate, 'timing_delta_ms': timing,
            'identical_rankings': all(q['same_ranking'] for q in per_query),
            'missing_rows': sorted(map(list, base_rows.keys() ^ cand_rows.keys())),
            'regressions': [q for q in per_query if q['regressions']],
            'improvements': [q for q in per_query if q['improvements']],
            'per_query': per_query}


def _summary_delta(b: dict, c: dict) -> dict:
    def diff(x, y):
        return None if x is None or y is None else y - x
    out = {k: {'base': b['quality_answerable'][k], 'candidate': c['quality_answerable'][k],
               'delta': diff(b['quality_answerable'][k], c['quality_answerable'][k])} for k in QUALITY_KEYS}
    for k in ('false_refusal_rate', 'false_acceptance_rate'):
        out[k] = {'base': b['answerability'][k], 'candidate': c['answerability'][k],
                  'delta': diff(b['answerability'][k], c['answerability'][k])}
    for k, path in (('mean_estimated_tokens', 'context'), ('cases_with_violations', 'integrity'),
                    ('distractor_before_evidence', 'distractors')):
        out[k] = {'base': b[path][k], 'candidate': c[path][k], 'delta': diff(b[path][k], c[path][k])}
    return out


def gate_failures(report: dict) -> list[str]:
    """Absolute checks for a single run (merge gate floor, not a quality target)."""
    failures = []
    for name, suite in report['suites'].items():
        s = suite['summary']
        if s['integrity']['cases_with_violations']:
            failures.append(f"{name}: integrity violations {s['integrity']['violations']}")
        if s['flags']['all_abstain']:
            failures.append(f'{name}: adapter abstained on every case')
        if s['flags']['never_abstains_on_unanswerable']:
            failures.append(f'{name}: adapter accepted every unanswerable case')
    return failures


def compare_gate_failures(diff: dict, require_identical: bool, max_p95_increase_ms: float | None) -> list[str]:
    failures = [f"{q['suite']}/{q['id']}: {'; '.join(q['regressions'])}" for q in diff['regressions']]
    if require_identical and not diff['identical_rankings']:
        failures.append('rankings differ (ranking-equivalent change required)')
    if max_p95_increase_ms is not None and (diff['timing_delta_ms']['warm_p95_ms'] or 0) > max_p95_increase_ms:
        failures.append(f"warm p95 increased by {diff['timing_delta_ms']['warm_p95_ms']:.2f} ms")
    if diff['missing_rows']:
        failures.append(f"rows missing from one report: {diff['missing_rows']}")
    return failures


# ------------------------------------------------------------------- peers

def _peer_items(data, source: str) -> list[dict]:
    rows = data.get('cases') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows:
        if not isinstance(row, dict) or not _str(row.get('query')):
            continue
        docs, chunks = set(), set()
        for e in row.get('evidence') or []:
            if not isinstance(e, dict):
                continue
            for d in ([e.get('doc_id')] if e.get('doc_id') else []) + list(e.get('doc_ids') or []):
                if isinstance(d, str):
                    docs.add(d)
            for s in e.get('support') or []:
                if isinstance(s, dict) and isinstance(s.get('chunk_id'), str):
                    chunks.add(s['chunk_id'])
            for cid in e.get('chunk_ids') or []:
                if isinstance(cid, str):
                    chunks.add(cid)
        docs.update(c.split('_', 1)[0] for c in chunks)
        items.append({'source': source, 'id': str(row.get('id', '')), 'query': row['query'],
                      'history': [t.get('content', '') for t in row.get('history') or [] if isinstance(t, dict)],
                      'unanswerable': row.get('unanswerable'), 'docs': sorted(docs), 'chunks': sorted(chunks)})
    return items


def load_peers(git_refs: list[str]) -> tuple[list[dict], list[str]]:
    """Read mentee 2-5 case files from the working tree and optional git refs, never writing them."""
    items, sources = [], []
    for path in sorted(ROOT.glob(PEER_GLOB)):
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        found = _peer_items(data, str(path.relative_to(ROOT)))
        if found:
            items += found
            sources.append(str(path.relative_to(ROOT)))
    for ref in git_refs:
        try:
            names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', ref, '--', 'evaluate'],
                                            cwd=ROOT, text=True, stderr=subprocess.DEVNULL).splitlines()
        except (OSError, subprocess.CalledProcessError):
            sources.append(f'{ref}: unavailable')
            continue
        for name in names:
            if not re.match(r'^evaluate/mentee[2-5]/.+\.json$', name):
                continue
            try:
                data = json.loads(subprocess.check_output(['git', 'show', f'{ref}:{name}'], cwd=ROOT,
                                                          stderr=subprocess.DEVNULL).decode('utf-8-sig'))
            except (OSError, ValueError, subprocess.CalledProcessError):
                continue
            found = _peer_items(data, f'{ref}:{name}')
            if found:
                items += found
                sources.append(f'{ref}:{name}')
    return items, sources


def overlaps(peers: list[dict], own: list[dict], corpus_docs: set[str], threshold: float = .5) -> list[dict]:
    found = []
    for p in peers:
        ptok = set(ev.tokens(p['query']))
        for o in own:
            otok = set(ev.tokens(o['query']))
            jaccard = len(ptok & otok) / len(ptok | otok) if ptok | otok else 0
            shared_chunks = sorted(set(p['chunks']) & set(o['chunks']))
            shared_docs = sorted(set(p['docs']) & set(o['docs']))
            kinds = []
            if ev.normalize(p['query']) == ev.normalize(o['query']):
                kinds.append('identical query')
            elif jaccard >= threshold:
                kinds.append(f'similar query (jaccard {jaccard:.2f})')
            if shared_chunks:
                kinds.append('shared evidence chunks')
            elif shared_docs and jaccard >= threshold / 2:
                kinds.append('shared evidence documents and related wording')
            if kinds:
                found.append({'peer': f"{p['source']}#{p['id']}", 'own': f"{o['source']}#{o['id']}",
                              'kinds': kinds, 'shared_chunks': shared_chunks, 'shared_docs': shared_docs})
    for p in peers:
        if p['docs'] and not set(p['docs']) <= corpus_docs:
            found.append({'peer': f"{p['source']}#{p['id']}", 'own': None,
                          'kinds': ['evidence documents not in production corpus (synthetic fixture?)'],
                          'shared_chunks': [], 'shared_docs': sorted(set(p['docs']) - corpus_docs)})
    return found


def own_items(cases_path: Path) -> list[dict]:
    items = []
    if cases_path.exists():
        data = json.loads(cases_path.read_text(encoding='utf-8-sig'))
        items += _peer_items(data, str(cases_path.relative_to(ROOT)) if cases_path.is_relative_to(ROOT)
                             else str(cases_path))
    questions = ev.read_json(QUESTIONS_PATH, comments=True)
    items += _peer_items(questions, 'evaluate/questions.json')
    return items


# ----------------------------------------------------------------- markdown

def _fmt(value, digits=3):
    if value is None:
        return 'n/a'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def _signed(value, digits=3):
    return 'n/a' if value is None else f'{value:+.{digits}f}'


def render_run(report: dict) -> str:
    env, inputs, timing = report['environment'], report['inputs'], report['timing']
    lines = [f"# Retrieval evaluation: {report['adapter']['name']}", '',
             f"Commit `{env.get('commit')}` ({'with' if env.get('tracked_changes') else 'no'} tracked changes), "
             f"Python {env['python']} on {env['platform']}.",
             f"Corpus `{inputs['corpus_sha256'][:16]}` ({inputs['chunks']} chunks, {inputs['documents']} documents), "
             f"config `{inputs['config_sha256'][:16]}`, top_k {report['settings']['top_k']}, "
             f"{report['settings']['repeat']} timing repetitions, order {report['settings']['order']}.",
             '', 'Scores are ranking scores, not probabilities. Quality metrics cover answerable cases only.', '',
             '## Efficiency', '', '| Cold load ms | Warm p50 ms | Warm p95 ms | Warm max ms | Timed calls |',
             '| ---: | ---: | ---: | ---: | ---: |',
             f"| {_fmt(timing['cold_load_ms'], 1)} | {_fmt(timing['warm_p50_ms'], 2)} | {_fmt(timing['warm_p95_ms'], 2)} "
             f"| {_fmt(timing['warm_max_ms'], 2)} | {timing['timed_calls']} |", '']
    for name, suite in report['suites'].items():
        s = suite['summary']
        lines += [f"## Suite `{name}` ({inputs['suites'][name]['items']} cases, sha `{inputs['suites'][name]['sha256'][:16]}`)",
                  '', '| Recall | Complete | RR | Precision | False refusal | False acceptance | Distractor first '
                  '| Mean tokens | Violations |', '| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
                  _summary_line(s), '']
        if s['flags']['all_abstain'] or s['flags']['never_abstains_on_unanswerable']:
            lines += [f"**Warning:** {', '.join(k for k, v in s['flags'].items() if v)}", '']
        lines += ['| Category | Cases | Recall | Complete | RR | Precision | False refusal | False acceptance '
                  '| Distractor first | Mean tokens | Violations |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for cat, cs in suite['by_category'].items():
            lines.append(f"| {cat} | {cs['cases']} " + _summary_line(cs))
        lines += ['', '| Case | Category | Abstained | Reason | Recall | Complete | RR | Precision | Distractors | Top IDs |',
                  '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
        for r in report['rows']:
            if r['suite'] != name:
                continue
            m = r['metrics']
            flag = ' (unanswerable)' if r['unanswerable'] else ''
            lines.append(f"| {r['id']}{flag} | {r['category']} | {_fmt(r['abstained'])} | {r['reason'] or ''} "
                         f"| {_fmt(m['evidence_recall'], 2)} | {_fmt(m['complete_evidence'])} | {_fmt(m['reciprocal_rank'], 2)} "
                         f"| {_fmt(m['context_precision'], 2)} | {m['distractor_hits']} | {', '.join(r['ranked'][:3])} |")
        lines.append('')
    return '\n'.join(lines)


def _summary_line(s: dict) -> str:
    q, a = s['quality_answerable'], s['answerability']
    return (f"| {_fmt(q['evidence_recall'])} | {_fmt(q['complete_evidence'])} | {_fmt(q['reciprocal_rank'])} "
            f"| {_fmt(q['context_precision'])} | {a['answerable_abstained']}/{a['answerable']} "
            f"| {a['unanswerable_accepted']}/{a['unanswerable']} | {s['distractors']['distractor_before_evidence']} "
            f"| {_fmt(s['context']['mean_estimated_tokens'], 0)} | {s['integrity']['cases_with_violations']} |")


def render_compare(diff: dict) -> str:
    lines = [f"# Comparison: {diff['base']} (base) vs {diff['candidate']} (candidate)", '']
    lines += [f'- Note: {n}' for n in diff['notes']] or ['- Inputs identical (corpus, suites, top_k).']
    t = diff['timing_delta_ms']
    lines += [f"- Identical rankings on every case: {_fmt(diff['identical_rankings'])}",
              f"- Timing delta ms: cold {_signed(t['cold_load_ms'], 1)}, warm p50 {_signed(t['warm_p50_ms'], 2)}, "
              f"warm p95 {_signed(t['warm_p95_ms'], 2)}", '']
    for suite, agg in diff['aggregate'].items():
        lines += [f'## Suite `{suite}`', '', '| Metric | Base | Candidate | Delta |', '| --- | ---: | ---: | ---: |']
        for k, v in agg['overall'].items():
            lines.append(f"| {k} | {_fmt(v['base'])} | {_fmt(v['candidate'])} | {_signed(v['delta'])} |")
        lines += ['', '| Category | Complete delta | Recall delta | Precision delta | False refusal delta '
                  '| False acceptance delta |', '| --- | ---: | ---: | ---: | ---: | ---: |']
        for cat, v in agg['by_category'].items():
            lines.append(f"| {cat} | {_signed(v['complete_evidence']['delta'])} | {_signed(v['evidence_recall']['delta'])} "
                         f"| {_signed(v['context_precision']['delta'])} | {_signed(v['false_refusal_rate']['delta'])} "
                         f"| {_signed(v['false_acceptance_rate']['delta'])} |")
        lines.append('')
    for title, key in (('Regressions', 'regressions'), ('Improvements', 'improvements')):
        lines += [f'## {title} ({len(diff[key])})', '']
        lines += [f"- `{q['suite']}/{q['id']}` ({q['category']}): {'; '.join(q[key])}" for q in diff[key]] or ['- none']
        lines.append('')
    return '\n'.join(lines)


# --------------------------------------------------------------------- cli

def _guard_output(path: Path | None) -> None:
    if path is None:
        return
    target = path.resolve()
    protected = {CASES_PATH.resolve(), QUESTIONS_PATH.resolve(), CONFIG_PATH.resolve(), Path(__file__).resolve()}
    if target in protected or target.is_relative_to((ROOT / 'backend' / 'data').resolve()) \
            or target.is_relative_to((ROOT / 'backend' / 'app').resolve()):
        raise HarnessError(f'refusing to write output over inputs, corpus or runtime code: {path}')


def _write(path: Path | None, text: str) -> None:
    if path is not None:
        _guard_output(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p_val = sub.add_parser('validate', help='verify fixture labels against the corpus')
    p_val.add_argument('--cases', type=Path, default=CASES_PATH)
    p_val.add_argument('--no-coverage', action='store_true', help='skip the minimum count/category checks')
    p_run = sub.add_parser('run', help='evaluate one adapter')
    p_run.add_argument('--adapter', default='production',
                       help=f'built-in {sorted(BUILTIN_ADAPTERS)}, module:callable or path.py:callable')
    p_run.add_argument('--suite', action='append', choices=('mentee1', 'dev', 'test'),
                       help='repeatable; default mentee1 and dev')
    p_run.add_argument('--cases', type=Path, default=CASES_PATH)
    p_run.add_argument('--top-k', type=int, default=5)
    p_run.add_argument('--repeat', type=int, default=3, help='timing repetitions; ranking uses repetition 1')
    p_run.add_argument('--order', choices=('id', 'file'), default='id')
    p_run.add_argument('--allow-test-split', action='store_true')
    p_run.add_argument('--json', type=Path)
    p_run.add_argument('--markdown', type=Path)
    p_run.add_argument('--gate', action='store_true', help='exit 1 on integrity violations or degenerate behavior')
    p_cmp = sub.add_parser('compare', help='compare two run reports')
    p_cmp.add_argument('base', type=Path)
    p_cmp.add_argument('candidate', type=Path)
    p_cmp.add_argument('--json', type=Path)
    p_cmp.add_argument('--markdown', type=Path)
    p_cmp.add_argument('--allow-mismatch', action='store_true')
    p_cmp.add_argument('--gate', action='store_true', help='exit 1 on any per-query regression')
    p_cmp.add_argument('--require-identical-rankings', action='store_true')
    p_cmp.add_argument('--max-p95-increase-ms', type=float)
    p_peer = sub.add_parser('peers', help='read other mentees\' cases and report overlaps')
    p_peer.add_argument('--git-ref', action='append', default=[], help='also read evaluate/mentee2-5 from this ref')
    p_peer.add_argument('--cases', type=Path, default=CASES_PATH)
    p_peer.add_argument('--json', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'compare':
            for path in (args.json, args.markdown):
                _guard_output(path)
            diff = compare(json.loads(args.base.read_text(encoding='utf-8')),
                           json.loads(args.candidate.read_text(encoding='utf-8')), args.allow_mismatch)
            _write(args.json, json.dumps(diff, indent=2) + '\n')
            text = render_compare(diff)
            _write(args.markdown, text + '\n')
            print(text)
            failures = compare_gate_failures(diff, args.require_identical_rankings, args.max_p95_increase_ms)
            if args.gate and failures:
                print('GATE FAILED:\n  ' + '\n  '.join(failures), file=sys.stderr)
                return 1
            return 0
        config, settings = load_config()
        corpus = load_corpus(config, settings)
        if args.command == 'validate':
            data = ev.read_json(args.cases)
            cases, errors = validate_cases(data, corpus, not args.no_coverage)
            warnings = []
            if not errors:
                for c in cases:
                    if not oracle_feasible(c, corpus, settings, settings.top_k):
                        warnings.append(f"{c['id']}: no indexable evidence selection fits top_k/budget/document cap")
                test_queries = {ev.normalize(q['query']) for q in ev.read_json(QUESTIONS_PATH, comments=True)
                                if isinstance(q, dict) and q.get('split') == 'test'}
                warnings += [f"{c['id']}: identical to a test-split question" for c in cases
                             if ev.normalize(c['query']) in test_queries]
            counts = Counter(c.get('category') for c in cases)
            print(json.dumps({'cases': len(cases), 'unanswerable': sum(c.get('unanswerable') is True for c in cases),
                              'by_category': dict(sorted(counts.items())), 'corpus_sha256': corpus.sha256,
                              'cases_sha256': sha256_bytes(args.cases.read_bytes()),
                              'errors': errors, 'warnings': warnings}, indent=2))
            return 1 if errors else 0
        if args.command == 'peers':
            _guard_output(args.json)
            peers, sources = load_peers(args.git_ref)
            found = overlaps(peers, own_items(args.cases), {c['doc_id'] for c in corpus.chunks})
            result = {'sources_read': sources, 'peer_cases': len(peers), 'overlaps': found}
            _write(args.json, json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            return 0
        for path in (args.json, args.markdown):
            _guard_output(path)
        from backend.app.retrieval import load_urls
        urls = load_urls(ROOT / config['registry_path'])
        suites = build_suites(args.suite or ['mentee1', 'dev'], args.cases, corpus, args.allow_test_split)
        report = run(load_adapter(args.adapter), suites, corpus, settings, urls, args.top_k, args.repeat, args.order)
        _write(args.json, json.dumps(report, indent=2) + '\n')
        _write(args.markdown, render_run(report) + '\n')
        print(json.dumps({'adapter': report['adapter']['name'], 'timing': report['timing'],
                          'suites': {n: s['summary'] for n, s in report['suites'].items()}}, indent=2))
        failures = gate_failures(report)
        if args.gate and failures:
            print('GATE FAILED:\n  ' + '\n  '.join(failures), file=sys.stderr)
            return 1
        return 0
    except (HarnessError, ValueError, TypeError, OSError) as exc:
        print(f'mentee1_eval: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
