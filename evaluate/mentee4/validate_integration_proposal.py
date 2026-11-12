"""Apply the proposal in memory and compare its index to the isolated adapter."""

import re
from pathlib import Path

from backend.app.retrieval import ROOT, _load
from backend.app.retrieval_support.precision import rerank
from backend.app.retrieval_support.query import rewrite
from evaluate import evaluate_chunks as ev
from evaluate.mentee4.adapter import search
from evaluate.mentee4.hard_cases import load_cases


def proposed_sources():
    """Strictly validate/apply this two-file unified diff without writing files."""
    lines = Path(__file__).with_name("integration-proposal.patch").read_text().splitlines(True)
    result = {}
    cursor = 0
    allowed = {"backend/app/retrieval_support/index.py", "backend/app/retrieval.py"}
    while cursor < len(lines):
        assert lines[cursor].startswith("--- a/")
        path = lines[cursor][6:].strip()
        assert path in allowed
        assert lines[cursor + 1].strip() == "+++ b/" + path
        source = (ROOT / path).read_text().splitlines(True)
        cursor += 2
        output, used = [], 0
        while cursor < len(lines) and lines[cursor].startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[cursor])
            assert match
            start = int(match[1]) - 1
            assert start >= used
            output.extend(source[used:start])
            used = start
            cursor += 1
            while cursor < len(lines) and not lines[cursor].startswith(("@@", "--- a/")):
                line = lines[cursor]
                assert line[0] in " +-"
                if line[0] in " -":
                    assert source[used] == line[1:], (path, used)
                    used += 1
                if line[0] in " +":
                    output.append(line[1:])
                cursor += 1
        output.extend(source[used:])
        result[path] = "".join(output)
    assert set(result) == allowed
    return result


def main():
    sources = proposed_sources()
    for path, text in sources.items():
        compile(text, path, "exec")
    namespace = {"__name__": "mentee4_proposed_index"}
    exec(compile(sources["backend/app/retrieval_support/index.py"], "proposed_index", "exec"), namespace)
    index, config, _, _ = _load()
    proposed = namespace["LexicalIndex"](index.chunks, index.s)
    corpus = ev.read_chunks(ROOT / config["chunks_path"])
    questions = ev.read_questions(ROOT / "evaluate/questions.json", corpus, "dev") + load_cases(corpus)
    for question in questions:
        query = rewrite(question["query"].strip()[:2000], None)
        assert proposed.search(query, 5) == index.search(query, 5), question["id"]
        assert proposed.search(query, 5, reranker=rerank) == search(
            index, query, use_precision=True), question["id"]
    for k in range(1, 9):
        query = "Computer Science plan 2020-2021 electives"
        assert proposed.search(query, k) == index.search(query, k)
        assert proposed.search(query, k, reranker=rerank) == search(
            index, query, top_k=k, use_precision=True)
    print(f"PASS: proposal compiles; baseline and reranked index parity on {len(questions)} dev cases.")
    print("PASS: top_k 1..8 preserved. Shared files were read only.")
    print("Service wiring was syntax-checked only; mentor must run integrated service tests after applying.")


if __name__ == "__main__":
    main()
