# Answer quality and session reliability

The interface includes searchable official-document browsing, linked citation
cards, answer word counts, Markdown download, browser-local history deletion,
mobile navigation and light/dark themes.

## Grounding contract

The provider prompt aims for 80 to 120 words with a hard validation ceiling of
275 words before a short confirmation note, keeping the response below 300 words.
Each claim needs a complete source sentence in every cited passage, with exact
withdrawal deadline phrases allowed for scoped calendar questions. Unsupported answers
fall back to extracted source sentences or abstain. Generic navigation sentences
are excluded from the extractive picker. Follow-ups are rewritten for both
retrieval and generation.

Chat validates the full answer before streaming citations and text. The retrieval
event reports passages considered, which can include passages the answer did not
cite. The default provider is extractive. Optional providers use the same source
checks. Source matching does not establish that a copied policy is current or
that it applies to a student's individual circumstances.

Regression coverage includes invented fees, unrelated claims with a real citation
ID, overlong replies, invalid or missing citations, source-only fallback and
matching stream and synchronous output.

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
