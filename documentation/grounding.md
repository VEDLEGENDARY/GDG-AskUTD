# Source fidelity

Every chat request runs retrieval before generation. Retrieval abstention skips the model entirely. Both streaming and non-streaming answers use the same validator, before any answer tokens are released.

Each cited claim must match a complete source sentence from every cited passage.
The match normalizes case, whitespace, and em dash formatting. It preserves
currency, negations, numbers and other punctuation. For session-specific
withdrawal deadlines the reader can use an exact date phrase within the source.
Unsupported wording falls back to extraction. The validator also checks that
answers to recognized AP and catalog elective comparisons cover the requested
rows. Missing evidence produces an abstention. The fixed policy confirmation
note is application guidance.

The stream emits a retrieval event containing passage IDs, distinct document count, elapsed milliseconds and retrieval status. The UI displays these independently of the final citations. This is an audit trail, not a confidence score.

Retrieval uses BM25, TF-IDF similarity and metadata coverage to admit candidates. The reranker adjusts their order for explicit program and catalog scope before diversity selection, document caps and the context budget. No embedding model or external search is required.

Source fidelity is not a guarantee of real-world correctness or completeness. Outdated, conflicting or incomplete documents remain limitations, and exact matching deliberately sacrifices paraphrasing. Use the source links to confirm critical details.

Validation: `py -m pytest backend/tests -q`, `npm test`, `npm run build`, `py scripts/eval_retrieval.py --split test`.
