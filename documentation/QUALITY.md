# Answer quality and session reliability

The interface includes searchable official-document browsing, linked citation
cards, answer word counts, Markdown download, browser-local history deletion,
mobile navigation and light/dark themes.

## Grounding contract

The provider prompt aims for 80 to 120 words with a hard validation ceiling of
275 words before a short confirmation note, keeping the response below 300 words.
Missing citations no longer receive a fabricated default citation. Every sentence
must contain a valid citation; numeric values must occur in the cited passage;
at least 30% of the claim's content terms must overlap its cited evidence. Invalid
answers fall back to extracted source sentences or abstain. Generic navigation
sentences are excluded from the extractive picker. Short follow-ups are rewritten
for both retrieval and generation.

The entire candidate is validated before text is released as SSE token events.
This trades live model-token latency for consistent validation. Failed candidates
are never partially shown. Citation checks and lexical overlap are heuristics,
not semantic entailment or proof of truth. The corpus is a snapshot, not live web
research. The default provider remains extractive; a configured Ollama or hosted
provider can generate paraphrases, subject to the same checks. No model was
trained or upgraded as part of this change.

Regression coverage includes invented fees, unrelated claims with a real citation
ID, overlong replies, invalid/missing citations, source-only fallback and matching
stream/final text. The held-out retrieval benchmark was not rerun or tuned.

## Power and connectivity

This development machine runs Windows. The pasted MacBook commands were not
executed and no global sleep/lid/power policy was changed. The official desktop
settings reference describes Prevent sleep while running for macOS and Linux:
https://learn.chatgpt.com/docs/reference/settings

For a temporary Windows idle-sleep request, run from the repository root:

```powershell
powershell -NoProfile -File scripts/keep-awake.ps1 -Minutes 30
```

The request ends on Ctrl+C, process exit, or the specified deadline (maximum two
hours). The display may still turn off. It does not prevent explicit sleep or lid
sleep, restore Wi-Fi, guarantee network continuity, or survive a shutdown. See
Microsoft's documented behavior:
https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate

The machine required administrator access to inspect `powercfg /requests`, so
system-wide power policy could not be audited. A scoped request was used during
implementation and released afterward. On a Mac, confirm supported lid-closed
operation for your exact hardware and power setup; do not treat `pmset` or a
keep-awake utility as a guarantee of lid-closed or network reliability.
