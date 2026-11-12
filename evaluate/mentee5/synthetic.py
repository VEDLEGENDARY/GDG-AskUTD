"""Deterministic synthetic corpora for mentee 5 scaling and parity checks (test-only).

Synthetic chunks never enter the production corpus and synthetic timings must be reported
separately from real-corpus timings.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRESS_PATH = HERE / 'stress_queries.json'

# A small vocabulary with a Zipf-like draw gives realistic document frequency skew.
_WORDS = ('registration tuition graduate undergraduate deadline refund financial aid transcript '
          'probation housing parking census withdrawal drop class course credit hours semester '
          'fall spring summer petition bursar registrar advisor degree plan catalog major minor '
          'gpa grade exam final schedule office policy procedure student faculty employee leave '
          'overtime holiday conduct hearing appeal sanction record privacy ferpa scholarship loan '
          'grant residency texas international visa orientation library computer science engineering '
          'mathematics physics biology chemistry elective prerequisite capstone thesis dissertation').split()


def _sentence(rng: random.Random, n: int, extra: list[str]) -> str:
    weights = [1/(r+1) for r in range(len(_WORDS))]
    words = rng.choices(_WORDS, weights=weights, k=n) + extra
    rng.shuffle(words)
    return ' '.join(words).capitalize() + '.'


def make_corpus(size: int, seed: int = 5) -> list[dict]:
    """Chunks with skewed term frequencies, shared doc IDs, rare tokens and metadata-only terms."""
    rng = random.Random(seed)
    rows = []
    for i in range(size):
        doc = f'syn{i // 7:05d}'
        rare = [f'rare{rng.randrange(size)}'] if rng.random() < .3 else []
        rows.append({
            'chunk_id': f'{doc}_c{i % 7}',
            'doc_id': doc,
            'text': _sentence(rng, rng.randint(8, 120), rare),
            'source_title': f'Synthetic {rng.choice(_WORDS)} guide' + (' metaonly' if i % 97 == 0 else ''),
            'section_heading': rng.choice(['', 'Overview', f'{rng.choice(_WORDS).title()} rules']),
        })
    return rows


def make_queries(size: int, count: int = 60, seed: int = 55) -> list[str]:
    """Mix of short, long, rare-term, metadata-only and unknown-term queries."""
    rng = random.Random(seed)
    queries = ['metaonly', 'metaonly guide', 'unknownterm zzz', f'rare{size // 2} rare{size // 3}']
    while len(queries) < count:
        n = rng.choice((1, 2, 3, 5, 8, 20))
        words = rng.choices(_WORDS, k=n)
        if rng.random() < .2:
            words.append(f'rare{rng.randrange(size)}')
        queries.append(' '.join(words))
    return queries


def stress_queries() -> list[str]:
    """Adversarial fixture queries with the very long template expanded."""
    out = []
    for row in json.loads(STRESS_PATH.read_text(encoding='utf-8')):
        q = row['query']
        out.append(' '.join([q.replace('@REPEAT@', '').strip()]*200) if q.startswith('@REPEAT@') else q)
    return out
