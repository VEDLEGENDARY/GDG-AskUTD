'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';

import {
  ArrowUp,
  BookMarked,
  Check,
  ChevronDown,
  Globe2,
  Library,
  Menu,
  PlusCircle,
  Search,
  Settings,
  Share2,
  ThumbsDown,
  ThumbsUp,
  X,
  ArrowUpRight,
  Download,
  Trash2,
  Compass,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import {
  sendFeedback,
  streamAnswer,
  type Citation,
  type Turn,
  type RetrievalTrace,
} from '@/lib/api';

type Message = {
  retrieval?: RetrievalTrace;
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  requestId?: string;
  abstained?: boolean;
  error?: string;
};

type Conversation = { id: string; title: string; messages: Message[] };

const STORAGE = 'askutd-conversations-v1';

function savedConversations(): Conversation[] {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE) || '[]');

    if (!Array.isArray(data)) return [];

    return data
      .filter(
        (c) =>
          typeof c?.id === 'string' &&
          typeof c?.title === 'string' &&
          Array.isArray(c.messages) &&
          c.messages.every(
            (m: Message) =>
              typeof m?.id === 'string' &&
              typeof m?.question === 'string' &&
              typeof m?.answer === 'string' &&
              Array.isArray(m.citations) &&
              m.citations.every(
                (c) =>
                  c &&
                  typeof c.n === 'number' &&
                  typeof c.title === 'string' &&
                  typeof c.section === 'string' &&
                  typeof c.snippet === 'string' &&
                  (c.source_url === null || typeof c.source_url === 'string'),
              ),
          ),
      )
      .slice(0, 30);
  } catch {
    return [];
  }
}

function sourceUrl(value: string | null): string | undefined {
  try {
    const url = new URL(value || '');
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function AnswerText({ message }: { message: Message }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-7">
      {message.answer.split(/(\[\d+\])/g).map((part, i) => {
        const marker = /^\[(\d+)\]$/.exec(part);

        const citation = marker && message.citations.find((c) => c.n === Number(marker[1]));

        return citation ? (
          <a
            className="font-bold text-[#12766b] underline dark:text-[#83d8c4]"
            key={i}
            href={`#${message.id}-source-${citation.n}`}
            aria-label={`Source ${citation.n}: ${citation.title}`}
          >
            {part}
          </a>
        ) : (
          part
        );
      })}
    </p>
  );
}

export default function AskUtdApp({ questionId }: { questionId?: string }) {
  const [catalog, setCatalog] = useState<
    { doc_id: string; title: string; source_url: string | null; chunks: number }[]
  >([]);

  const [catalogOpen, setCatalogOpen] = useState(false);

  const [catalogQuery, setCatalogQuery] = useState('');

  const [health, setHealth] = useState<{ documents: number; chunks: number; llm: string } | null>(
    null,
  );

  const [dark, setDark] = useState(false);

  const [ready, setReady] = useState(false);

  const [conversations, setConversations] = useState<Conversation[]>([]);

  const [selected, setSelected] = useState<string | null>(null);

  const [query, setQuery] = useState('');

  const [question, setQuestion] = useState('');

  const [suggestions, setSuggestions] = useState<string[]>([]);

  const [pending, setPending] = useState(false);

  const [sidebar, setSidebar] = useState(false);

  const [notice, setNotice] = useState('');

  const [ratings, setRatings] = useState<Record<string, string>>({});

  const [ratingPending, setRatingPending] = useState<string | null>(null);

  const busy = useRef(false);

  const bottom = useRef<HTMLDivElement>(null);

  const conversation = conversations.find((c) => c.id === selected);

  const messages = conversation?.messages || [];

  useEffect(() => {
    const saved = savedConversations();

    setConversations(saved);

    setSelected(saved.some((c) => c.id === questionId) ? questionId! : null);

    try {
      setDark(localStorage.getItem('askutd-theme') === 'dark');
    } catch {
      /* Storage is optional. */
    }

    setReady(true);

    const controller = new AbortController();

    fetch('/api/health', { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => {});

    fetch('/api/documents', { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (Array.isArray(data)) setCatalog(data);
      })
      .catch(() => {});

    fetch('/api/suggestions', { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error();

        const data = await r.json();

        if (Array.isArray(data)) setSuggestions(data.filter((x) => typeof x === 'string'));
      })
      .catch(() => {});

    return () => controller.abort();
  }, [questionId]);

  useEffect(() => {
    if (!ready) return;

    document.documentElement.classList.toggle('dark', dark);

    try {
      localStorage.setItem('askutd-theme', dark ? 'dark' : 'light');
    } catch {
      /* Theme works without storage. */
    }
  }, [dark, ready]);

  useEffect(() => {
    if (!ready || pending) return;

    try {
      localStorage.setItem(STORAGE, JSON.stringify(conversations));
    } catch {
      setNotice(
        'Your browser could not save this conversation. It is still available until you leave.',
      );
    }
  }, [conversations, ready, pending]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, pending]);

  function updateMessage(chatId: string, id: string, update: (m: Message) => Message) {
    setConversations((items) =>
      items.map((c) =>
        c.id === chatId
          ? { ...c, messages: c.messages.map((m) => (m.id === id ? update(m) : m)) }
          : c,
      ),
    );
  }

  async function ask(value: string) {
    value = value.trim();

    if (!value || value.length > 500 || busy.current || !ready) return;

    busy.current = true;

    setPending(true);

    setNotice('');

    setQuestion('');

    setSidebar(false);

    const chatId = selected || crypto.randomUUID();

    const id = crypto.randomUUID();

    const history: Turn[] = messages
      .filter((m) => !m.error && m.answer)
      .flatMap((m): Turn[] => [
        { role: 'user', content: m.question },
        { role: 'assistant', content: m.answer.slice(0, 4000) },
      ])
      .slice(-6);

    const message: Message = { id, question: value, answer: '', citations: [] };

    setSelected(chatId);

    setConversations((items) =>
      selected
        ? items.map((c) =>
            c.id === chatId ? { ...c, messages: [...c.messages.slice(-19), message] } : c,
          )
        : [{ id: chatId, title: value, messages: [message] }, ...items].slice(0, 30),
    );

    try {
      await streamAnswer(value, history, (update) =>
        updateMessage(chatId, id, (m) => ({
          ...m,
          answer: m.answer + (update.text || ''),

          citations: update.citations ?? m.citations,
          requestId: update.requestId ?? m.requestId,

          abstained: update.abstained ?? m.abstained,
          retrieval: update.retrieval ?? m.retrieval,
        })),
      );
    } catch (error) {
      updateMessage(chatId, id, (m) => ({
        ...m,
        error: error instanceof Error ? error.message : 'Unable to connect. Please try again.',
      }));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  function exportConversation() {
    const text = messages
      .map(
        (m) =>
          `## ${m.question}\n\n${m.answer}\n\n${m.citations.map((c) => `[${c.n}] ${c.title}: ${sourceUrl(c.source_url) || 'Link unavailable'}`).join('\n')}`,
      )
      .join('\n\n---\n\n');

    const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }));

    const link = document.createElement('a');
    link.href = url;
    link.download = 'askutd-conversation.md';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  function newConversation() {
    if (busy.current) return;
    setSelected(null);
    setQuestion('');
    setSidebar(false);
    setNotice('');
  }

  async function rate(message: Message, rating: 'up' | 'down') {
    if (!message.requestId || ratingPending) return;

    setRatingPending(message.id);

    try {
      await sendFeedback(message.requestId, rating);
      setRatings((r) => ({ ...r, [message.id]: rating }));
      setNotice('Thanks for your feedback.');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Feedback could not be saved.');
    } finally {
      setRatingPending(null);
    }
  }

  async function share() {
    const text = messages
      .filter((m) => m.answer && !m.error)
      .map(
        (m) =>
          `${m.question}\n\n${m.answer}\n\n${m.citations.map((c) => `[${c.n}] ${c.title}${sourceUrl(c.source_url) ? `: ${c.source_url}` : ''}`).join('\n')}`,
      )
      .join('\n\n');

    try {
      await navigator.clipboard.writeText(text);
      setNotice('Answer and sources copied.');
    } catch {
      setNotice('Clipboard access is unavailable. Select the answer text to copy it.');
    }
  }

  return (
    <main className="app-shell min-h-screen bg-[#f7f9fa] text-[#142a38] dark:bg-[#0b1b28] dark:text-[#f7f9fa]">
      <div className="flex h-dvh min-h-[500px]">
        <nav
          aria-label="Main navigation"
          className="app-rail flex w-20 shrink-0 flex-col items-center justify-between border-r border-[#dce5e8] bg-[#edf2f3] py-6 dark:border-[#233c4c] dark:bg-[#142a38]"
        >
          <div className="flex flex-col gap-6">
            <button
              className="rail-button font-bold"
              aria-label="New conversation"
              disabled={pending}
              onClick={newConversation}
            >
              <Compass size={26} />
            </button>
            <button
              className="rail-button"
              aria-label="Open conversation history"
              onClick={() => setSidebar(!sidebar)}
            >
              <Library />
            </button>
          </div>

          <button
            className="rail-button"
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            onClick={() => setDark(!dark)}
          >
            <Settings />
          </button>
        </nav>

        <aside
          className={`history-panel z-30 flex w-[296px] shrink-0 flex-col border-r border-[#dce5e8] bg-[#ffffff] p-6 dark:border-[#233c4c] dark:bg-[#142a38] ${sidebar ? 'mobile-open' : ''}`}
        >
          <div className="mb-6 flex items-center justify-between">
            <button onClick={newConversation} disabled={pending} className="text-2xl font-bold">
              ask<span className="brand-accent">utd</span>
              <span className="brand-dot">.</span>
            </button>
            <button
              aria-label="Close sidebar"
              onClick={() => setSidebar(false)}
              className="icon-action lg:hidden"
            >
              <X />
            </button>
          </div>

          <button
            onClick={newConversation}
            disabled={pending}
            className="mb-5 flex items-center gap-2 rounded-full bg-[#12766b] px-4 py-3 font-bold text-white disabled:opacity-50"
          >
            <PlusCircle size={20} />
            New question
          </button>

          <label className="mb-6 flex items-center gap-2 rounded-full border border-[#dce5e8] bg-white px-3 py-2 text-[#475569]">
            <Search size={18} />
            <input
              aria-label="Search conversations"
              className="min-w-0 bg-transparent text-sm outline-none"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search conversations"
            />
          </label>

          <h2 className="mb-3 flex items-center gap-2 font-bold">
            <Library size={20} />
            Your conversations
          </h2>

          <div className="flex-1 overflow-y-auto">
            {conversations
              .filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
              .map((c) => (
                <button
                  disabled={pending}
                  key={c.id}
                  onClick={() => {
                    setSelected(c.id);
                    setSidebar(false);
                  }}
                  className={`history-link w-full text-left ${c.id === selected ? 'history-current' : ''}`}
                  title={c.title}
                >
                  {c.title}
                </button>
              ))}
            {!conversations.length && (
              <p className="text-sm opacity-70">Your questions will appear here.</p>
            )}
          </div>

          <button className="catalog-button" onClick={() => setCatalogOpen(true)}>
            <BookMarked size={18} />
            <span>
              Explore the source library
              <small>
                {health
                  ? `${health.documents} documents, one place`
                  : 'Official UT Dallas documents'}
              </small>
            </span>
            <ArrowUpRight size={17} />
          </button>
          <p className="mt-4 text-xs opacity-60">Private to this browser.</p>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b border-[#dce5e8]/50 px-6 dark:border-[#233c4c]">
            <button
              className="icon-action lg:hidden"
              aria-label="Open sidebar"
              onClick={() => setSidebar(true)}
            >
              <Menu />
            </button>

            <span className="workspace-label">CAMPUS INTELLIGENCE</span>
            <span className="min-w-0 flex-1 truncate text-sm font-bold">
              {conversation?.title || 'Explore. Ask. Verify.'}
            </span>

            {!!messages.length && (
              <button
                aria-label="Download conversation"
                onClick={exportConversation}
                disabled={pending}
                className="icon-action"
              >
                <Download size={18} />
              </button>
            )}
            {!!messages.length && (
              <button
                className="flex items-center gap-2 text-sm"
                onClick={share}
                disabled={pending}
              >
                <Share2 size={17} />
                Copy answer
              </button>
            )}
          </header>

          <div className="answer-scroll flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-6 py-10 sm:px-10">
              {!messages.length && (
                <section className="welcome-panel">
                  <div className="hero-emblem">
                    <Compass size={44} strokeWidth={1} />
                    <span className="orbit orbit-one" />
                    <span className="orbit orbit-two" />
                  </div>
                  <p className="mb-3 text-sm font-bold uppercase tracking-widest text-[#12766b] dark:text-[#83d8c4]">
                    THE CAMPUS KNOWLEDGE WORKSPACE
                  </p>
                  <h1 className="mb-4 text-4xl font-bold tracking-tight">
                    Your campus.
                    <br />
                    <span className="hero-serif">Connected.</span>
                  </h1>
                  <p className="mb-8 leading-7 opacity-70">
                    Less searching. More knowing. Your guide to registration, financial aid, and
                    everything in between. Grounded in UT Dallas sources.
                  </p>
                  <div className="knowledge-stats">
                    <div>
                      <strong>{health?.documents ?? '—'}</strong>
                      <span>indexed documents</span>
                    </div>
                    <div>
                      <strong>{health?.chunks?.toLocaleString() ?? '—'}</strong>
                      <span>searchable passages</span>
                    </div>
                    <div>
                      <ShieldCheck size={23} />
                      <span>Source-matched answers</span>
                    </div>
                  </div>
                  <div className="suggestion-grid grid gap-3 sm:grid-cols-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        disabled={pending || !ready}
                        onClick={() => void ask(s)}
                        className="rounded-2xl border border-[#dce5e8] bg-[#ffffff] p-4 text-left text-sm transition hover:border-[#12766b] dark:border-[#2a4557] dark:bg-[#142a38]"
                      >
                        <span className="suggestion-icon">
                          <ArrowUpRight size={18} />
                        </span>
                        {s}
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {messages.map((message, index) => (
                <article
                  className="answer-article mb-10"
                  key={message.id}
                  aria-busy={pending && index === messages.length - 1}
                >
                  <h1 className="mb-6 text-2xl font-bold leading-snug">{message.question}</h1>

                  <h2 className="mb-3 flex items-center gap-2 font-bold">
                    <Sparkles size={19} />
                    From the documents
                  </h2>

                  {message.abstained && (
                    <p className="mb-3 text-xs font-bold uppercase tracking-wide opacity-60">
                      Not enough information in our sources
                    </p>
                  )}

                  {message.retrieval && (
                    <details className="retrieval-trace">
                      <summary>
                        <ShieldCheck size={15} />
                        Retrieval trail{' '}
                        <span>
                          {message.retrieval.passages} passages · {message.retrieval.elapsed_ms} ms
                        </span>
                      </summary>
                      <p>
                        {message.retrieval.documents} documents retrieved.{' '}
                        {message.retrieval.status === 'insufficient'
                          ? 'Evidence did not meet the retrieval threshold.'
                          : 'These passages were considered. The answer shows its own citations.'}
                      </p>
                      <code>
                        {message.retrieval.chunks.join(' / ') || 'No supporting passages'}
                      </code>
                    </details>
                  )}
                  <AnswerText message={message} />
                  {!pending && !message.error && (
                    <div className="answer-meta">
                      <ShieldCheck size={14} />
                      {message.abstained ? 'Evidence insufficient' : 'Source-matched answer'}
                      <span>{message.answer.trim().split(/\s+/).filter(Boolean).length} words</span>
                    </div>
                  )}

                  {pending && index === messages.length - 1 && (
                    <p role="status" className="mt-3 text-sm opacity-60">
                      {message.retrieval
                        ? 'Checking the answer against retrieved sources…'
                        : 'Finding relevant UT Dallas sources…'}
                    </p>
                  )}

                  {message.error && (
                    <div role="alert" className="mt-4 rounded-xl border border-red-400 p-4 text-sm">
                      <p>{message.error}</p>
                      <button
                        disabled={pending}
                        onClick={() => void ask(message.question)}
                        className="mt-2 font-bold underline"
                      >
                        Retry question
                      </button>
                    </div>
                  )}

                  {!!message.citations.length && (
                    <details className="mt-5" open>
                      <summary className="mb-3 flex cursor-pointer items-center gap-2 font-bold">
                        <BookMarked size={19} />
                        Sources ({message.citations.length})<ChevronDown size={16} />
                      </summary>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {message.citations.map((c) => (
                          <div
                            id={`${message.id}-source-${c.n}`}
                            key={`${c.n}-${c.chunk_id}`}
                            className="rounded-2xl border border-[#dce5e8] bg-[#ffffff] p-4 text-xs dark:border-[#2a4557] dark:bg-[#142a38]"
                          >
                            {sourceUrl(c.source_url) ? (
                              <a
                                href={sourceUrl(c.source_url)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-bold underline"
                              >
                                [{c.n}] {c.title}
                                <Globe2 className="ml-1 inline" size={13} />
                              </a>
                            ) : (
                              <p className="font-bold">
                                [{c.n}] {c.title}
                              </p>
                            )}
                            <p className="mt-2 opacity-70">{c.section}</p>
                            <p className="mt-2 leading-5">{c.snippet}</p>
                            {!sourceUrl(c.source_url) && (
                              <p className="mt-2 opacity-60">Source link unavailable</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {message.requestId &&
                    !message.error &&
                    !(pending && index === messages.length - 1) && (
                      <div className="mt-4 flex items-center gap-3">
                        <span className="text-xs opacity-60">Was this helpful?</span>
                        {(['up', 'down'] as const).map((rating) => (
                          <button
                            key={rating}
                            disabled={!!ratingPending || !!ratings[message.id]}
                            aria-label={rating === 'up' ? 'Helpful answer' : 'Unhelpful answer'}
                            aria-pressed={ratings[message.id] === rating}
                            onClick={() => void rate(message, rating)}
                            className="icon-action disabled:opacity-50"
                          >
                            {ratings[message.id] === rating ? (
                              <Check size={17} />
                            ) : rating === 'up' ? (
                              <ThumbsUp size={17} />
                            ) : (
                              <ThumbsDown size={17} />
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                </article>
              ))}
              <div ref={bottom} />
            </div>
          </div>

          {conversation && !pending && (
            <button
              className="delete-conversation"
              onClick={() => {
                setConversations((items) => items.filter((c) => c.id !== selected));
                setSelected(null);
              }}
            >
              <Trash2 size={14} />
              Delete this conversation
            </button>
          )}

          <footer className="mx-auto w-full max-w-3xl px-6 pb-5 sm:px-10">
            {notice && (
              <p role="status" className="mb-3 text-sm">
                {notice}
              </p>
            )}

            <form
              onSubmit={submit}
              className="composer-form flex items-center gap-3 rounded-full border border-[#dce5e8] bg-[#ffffff] p-2 pl-5 shadow-sm dark:border-[#2a4557] dark:bg-[#142a38]"
            >
              <input
                aria-label="Ask a campus question"
                maxLength={500}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={pending || !ready}
                placeholder={messages.length ? 'Ask a follow-up…' : 'Ask a campus question…'}
                className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none disabled:opacity-50"
              />

              <button
                aria-label="Send question"
                disabled={!question.trim() || pending || !ready}
                className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#12766b] text-white disabled:opacity-40"
              >
                <ArrowUp size={22} />
              </button>
            </form>
            <p className="mt-3 text-center text-[11px] opacity-60">
              Specific answers. Visible sources. Always confirm critical dates with UT Dallas.
            </p>
          </footer>
        </section>
      </div>

      {catalogOpen && (
        <div className="catalog-backdrop" onClick={() => setCatalogOpen(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label="Source library"
            className="catalog-modal"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setCatalogOpen(false);
              if (e.key === 'Tab') {
                const nodes = e.currentTarget.querySelectorAll<HTMLElement>(
                  'button:not(:disabled), input, a[href]',
                );
                const first = nodes[0],
                  last = nodes[nodes.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <header>
              <div>
                <p className="eyebrow">THE KNOWLEDGE BEHIND THE ANSWERS</p>
                <h2>Source library</h2>
              </div>
              <button
                autoFocus
                aria-label="Close source library"
                onClick={() => setCatalogOpen(false)}
                className="icon-action"
              >
                <X />
              </button>
            </header>
            <label className="catalog-search">
              <Search size={18} />
              <input
                aria-label="Search sources"
                placeholder="Find a policy, office, or catalog…"
                value={catalogQuery}
                onChange={(e) => setCatalogQuery(e.target.value)}
              />
            </label>
            <p className="catalog-count">
              {
                catalog.filter((d) => d.title.toLowerCase().includes(catalogQuery.toLowerCase()))
                  .length
              }{' '}
              documents
            </p>
            <div className="catalog-results">
              {catalog
                .filter((d) => d.title.toLowerCase().includes(catalogQuery.toLowerCase()))
                .map((d) => (
                  <div key={d.doc_id}>
                    <BookMarked size={18} />
                    <span>
                      {sourceUrl(d.source_url) ? (
                        <a href={sourceUrl(d.source_url)} target="_blank" rel="noopener noreferrer">
                          {d.title}
                          <ArrowUpRight size={14} />
                        </a>
                      ) : (
                        d.title
                      )}
                      <small>
                        {d.chunks} passages ·{' '}
                        {sourceUrl(d.source_url) ? 'Source available' : 'Source link unavailable'}
                      </small>
                    </span>
                  </div>
                ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
