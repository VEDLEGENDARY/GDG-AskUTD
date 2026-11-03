# Combined semantic chunk corpus

Merged `origin/lokesh-semantic-chunking` into main while retaining one complete
JSON output per document, with 59 documents from each contributor.

- Lokesh: doc001 through doc063, except doc005, doc016, doc017, and doc026.
- Nandhan (existing main): doc005, doc016, doc017, doc026, and doc064 through doc118.
- doc118, like doc016/doc017/doc026, exists only on main and is retained.
- Each selected JSON is kept byte-for-byte from its source branch, including its
  original filename, chunk text, IDs, and metadata. Alternate JSONs for the same
  document are excluded so the retrieval loader sees no duplicate chunk IDs.
- Lokesh's `fill_chunk_counts.py` is included for future validation/count updates.

This is a split by document count, not by chunk count. The contributors use
different chunk sizes, so their total chunk counts differ.

The academic policies output (doc005) is retained from main because its honors
evidence remains compatible with the existing retrieval benchmark.

## Documents 119 to 169

Added from the `Ariana-docs` branch with `add_documents.py`. Each PDF was
extracted, cleaned of browser headers and repeated menu lines, split into
sentence-aligned chunks of about 120 words, and listed in
`backend/data/doc_sources.json`.
