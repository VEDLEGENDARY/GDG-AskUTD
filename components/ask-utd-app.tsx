'use client';

import Image from 'next/image';
import Link from 'next/link';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  ArrowUp, BookMarked, ChevronDown, ChevronUp, CircleHelp, Clock3,
  Globe2, Home, Library, Menu, PlusCircle, Search,
  Settings, Share2, UserRound, X, Lightbulb,
} from 'lucide-react';

type HistoryItem = { title: string; slug: string };
const historyItems: HistoryItem[] = [
  { title: 'Hackign FBI server with raspberry pie', slug: 'fbi-server' },
  { title: 'COMPsci SICP tutorial course', slug: 'sicp-tutorial' },
  { title: 'Proxy failure troubleshooting', slug: 'proxy-failure-troubleshooting' },
  { title: 'Wake me up when september ends chord', slug: 'september-ends' },
  { title: 'Best OASIS songs top 100 all time', slug: 'oasis-songs' },
  { title: 'Fix SSL/TLS Error', slug: 'ssl-tls-error' },
  { title: 'React component quick fix', slug: 'react-component' },
  { title: 'Nextjs 18 documentations', slug: 'nextjs-docs' },
  { title: 'How to get healthy in 1 hour', slug: 'healthy-in-one-hour' },
];

const sources = [
  { title: 'Do androids dream of electric sheep?', site: 'www.philipkdick.com' },
  { title: 'Androids explained: Why LLMs will rule the world', site: 'www.dailyllm.com' },
  { title: 'View 87+ more external sources', site: 'View all sources' },
  { title: 'What makes a machine conscious?', site: 'www.scienceweekly.org' },
  { title: 'Dreams and artificial intelligence', site: 'www.neuroscience.edu' },
];

function RailButton({ label, children, active = false, onClick }: { label: string; children: React.ReactNode; active?: boolean; onClick?: () => void }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} className={`rail-button ${active ? 'rail-active' : ''}`}>{children}</button>;
}

export default function AskUtdApp({ questionId, questionTitle }: { questionId: string; questionTitle: string }) {
  const [dark, setDark] = useState(false);
  const [query, setQuery] = useState('');
  const [followUp, setFollowUp] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(true);
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [toast, setToast] = useState('');
  const [followUps, setFollowUps] = useState<string[]>([]);

  useEffect(() => {
    const saved = window.localStorage.getItem('askutd-theme');
    setDark(saved === 'dark');
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    if (typeof window !== 'undefined') window.localStorage.setItem('askutd-theme', dark ? 'dark' : 'light');
  }, [dark]);

  const filteredHistory = useMemo(() => historyItems.filter((item) => item.title.toLowerCase().includes(query.toLowerCase())), [query]);
  const visibleSources = sourcesExpanded ? sources : sources.slice(0, 3);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(''), 2400);
  }
  async function shareAnswer() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      notify('Link copied to clipboard');
    } catch { notify('Ready to share this answer'); }
  }
  function submitFollowUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = followUp.trim();
    if (!value) return;
    setFollowUps((items) => [...items, value]);
    setFollowUp('');
    notify('Follow-up added to this conversation');
  }

  return (
    <main className="app-shell min-h-screen w-full overflow-hidden bg-[#fefae0] text-[#252422] dark:bg-[#252422] dark:text-[#fefae0]">
      <div className="flex h-screen min-h-[640px] w-full">
        <nav aria-label="Main navigation" className="app-rail z-20 flex w-20 shrink-0 flex-col items-center justify-between border-r border-[#d4ce9a] bg-[#ede8b8] px-4 py-6 dark:border-[#3d3a36] dark:bg-[#2e2c29]">
          <div className="flex flex-col items-center gap-8">
            <Link aria-label="ASK-UTD home" href="/androids-dream" className="brand-mark flex size-8 items-center justify-center rounded-full bg-white shadow-[0_4px_8px_rgba(79,70,229,.1)] dark:rounded-xl dark:bg-[#4f46e5]"></Link>
            <div className="flex flex-col gap-4">
              <RailButton label="Home" active><Home size={23} strokeWidth={2.1} /></RailButton>
              <RailButton label="Your library"><UserRound size={23} strokeWidth={2.1} /></RailButton>
            </div>
          </div>
          <div className="flex flex-col items-center gap-4">
            <RailButton label={dark ? 'Switch to light mode' : 'Switch to dark mode'} onClick={() => setDark(!dark)}><Settings size={23} strokeWidth={2.1} /></RailButton>
            <button aria-label="Your profile" className="size-12 overflow-hidden rounded-full ring-2 ring-transparent transition hover:ring-[#e97600]">
              <Image src="/images/avatar.png" alt="Profile" width={48} height={48} priority className="size-full object-cover" />
            </button>
          </div>
        </nav>

        <aside className={`history-panel z-30 flex w-[296px] shrink-0 flex-col justify-between overflow-hidden border-r border-[#d4ce9a] bg-[#f5f0c0] dark:border-[#3d3a36] dark:bg-[#2e2c29] ${mobileSidebarOpen ? 'mobile-open' : ''}`}>
          <div>
            <div className="border-b border-[#d4ce9a] px-6 py-7 dark:border-[#3d3a36]">
              <div className="mb-4 flex items-center justify-between">
                <Link href="/androids-dream" className="text-2xl font-bold leading-8 tracking-[-.03em] text-[#252422] dark:text-[#fefae0]">💫 ASK-UTD</Link>
                <button aria-label="Close sidebar" onClick={() => setMobileSidebarOpen(false)} className="icon-action lg:hidden"><X size={20} /></button>
              </div>
              <label className="flex h-10 items-center gap-3 rounded-full border border-[#cbd5e1] bg-white px-3 text-[#475569] transition-colors focus-within:border-[#8c8470]">
                <input aria-label="Search conversations" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search anything..." className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[#475569]" />
                <Search aria-hidden="true" size={20} strokeWidth={2} />
              </label>
            </div>
            <div className="pt-4">
              <button type="button" onClick={() => setLibraryOpen(!libraryOpen)} aria-expanded={libraryOpen} className="flex w-full items-center gap-3 px-6 py-4 text-left">
                <Library size={22} strokeWidth={2.2} /><span className="flex-1 text-lg font-bold">Library</span>{libraryOpen ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
              </button>
              {libraryOpen && <div className="flex flex-col px-6 py-2 pl-9">
                {filteredHistory.map((item) => <Link key={item.slug} href={`/${item.slug}`} onClick={() => setMobileSidebarOpen(false)} className={`history-link ${item.slug === questionId ? 'history-current' : ''}`} title={item.title}>{item.title}</Link>)}
                {filteredHistory.length === 0 && <p className="px-4 py-3 text-sm text-[#8c8470]">No conversations found.</p>}
              </div>}
            </div>
          </div>
          <div className="hidden" aria-hidden="true" />
        </aside>

        <section className="workspace relative flex min-w-0 flex-1 flex-col bg-[#fefae0] dark:bg-[#252422]">
          <header className="flex h-12 shrink-0 items-center gap-4 overflow-hidden px-6">
            <button aria-label="Open conversation history" onClick={() => setMobileSidebarOpen(true)} className="icon-action lg:hidden"><Menu size={20} /></button>
            <div className="flex min-w-0 flex-1 items-center gap-2 text-sm font-bold tracking-[-.01em]">
              <UserRound className="shrink-0 text-[#5c5648] dark:text-[#c3bdad]" size={20} strokeWidth={2} />
              <span className="truncate">{questionTitle}</span>
            </div>
            <div className="flex shrink-0 items-center gap-4">
              <span className="hidden items-center gap-1 text-xs font-medium sm:flex"><Clock3 size={16} className="text-[#8c8470]" />22 hours ago</span>
              <button type="button" onClick={shareAnswer} className="inline-flex h-8 items-center gap-2 rounded-full bg-[#e97600] px-3 text-sm font-bold text-white transition hover:bg-[#cb6400] active:scale-95" aria-label="Share this answer"><Share2 size={16} strokeWidth={2.2} />Share</button>
            </div>
          </header>

          <div className="answer-scroll flex-1 overflow-y-auto">
            <article className="answer-column mx-auto flex w-[min(562px,calc(100%-40px))] flex-col gap-8 px-0 pb-8 pt-8 min-[1100px]:ml-[min(96px,7vw)] min-[1100px]:mr-0">
              <h1 className="px-6 text-[30px] font-bold leading-[1.27] tracking-[-.04em] text-[#252422] dark:text-[#fefae0]">{questionId === 'androids-dream' ? 'Do androids dream of electric sheep or not? Explained in ELI5' : questionTitle}</h1>

              <section aria-labelledby="sources-heading" className="flex flex-col gap-3 px-6">
                <h2 id="sources-heading" className="flex items-center gap-2 text-base font-bold"><BookMarked size={22} strokeWidth={2.1} className="text-[#5c5648] dark:text-[#c3bdad]" />Sources</h2>
                <div className="grid grid-cols-[157px_minmax(0,1fr)_minmax(0,1fr)] gap-2">
                  {visibleSources.map((source, index) => <a key={source.site} href={index === 0 ? 'https://philipkdick.com/' : '#sources'} onClick={(e) => { if (index > 0) { e.preventDefault(); if (index === 2) setSourcesExpanded(!sourcesExpanded); else notify(`Opening ${source.site}`); } }} className="source-card group flex min-h-[88px] flex-col justify-between rounded-2xl border border-[#d4ce9a] bg-[#f5f0c0] p-3 transition hover:-translate-y-0.5 hover:border-[#e97600] hover:shadow-sm dark:border-[#4a4742] dark:bg-[#2e2c29] dark:hover:border-[#e97600]">
                    <span className="line-clamp-2 text-xs font-medium leading-4 text-[#252422] dark:text-[#fefae0]">{source.title}</span>
                    <span className="flex items-center gap-1 text-[10px] font-medium text-[#5c5648] dark:text-[#c3bdad]"><Globe2 size={14} />{source.site}</span>
                  </a>)}
                </div>
              </section>

              <section aria-labelledby="answer-heading" className="flex flex-col gap-3 px-6">
                <h2 id="answer-heading" className="flex items-center gap-2 text-base font-bold"><Lightbulb size={23} strokeWidth={2.1} className="text-[#5c5648] dark:text-[#c3bdad]" />Answer</h2>
                <div className="answer-copy text-sm leading-[1.6] text-[#5c5648] dark:text-[#c3bdad]">
                  <p>Current State of AI:</p>
                  <ul className="list-disc pl-[21px]">
                    <li>Lack of Subjective Experience: Presently, AI lacks the capacity for subjective experience. While AI can process vast amounts of information and perform complex tasks, it doesn&apos;t have personal experiences or emotions.</li>
                    <li>Mimicking Human Behavior: Some AI systems are designed to mimic human behavior, including aspects of creativity and association, but this mimicry doesn&apos;t equate to actual dreaming.</li>
                  </ul>
                  <p className="mt-5">Future Possibilities:</p>
                  <ul className="list-disc pl-[21px]">
                    <li>Advancements in AI: Future developments in AI and neuroscience might bring us closer to creating machines with more sophisticated forms of processing. However, the creation of genuine subjective experiences in machines remains speculative and raises profound ethical and philosophical questions.</li>
                    <li>Artificial Consciousness Research: Research into artificial consciousness explores whether it might be possible to create machines that possess a form of self-awareness or subjective experience. If achieved, such machines might have the capability for experiences analogous to dreaming.</li>
                  </ul>
                  <p className="mt-5">Conclusion</p>
                  <p>From a current scientific and technological standpoint, androids do not dream of electric sheep. They lack the biological and neurological foundations required for dreaming as humans experience it.</p>
                  <p className="mt-5">However, advances in AI could potentially lead to systems that simulate aspects of dreaming or creativity, though these would still be fundamentally different from human dreams. The question remains a compelling intersection of philosophy, science fiction, and emerging technology.</p>
                </div>
                {followUps.map((question, index) => <div key={`${question}-${index}`} className="mt-4 rounded-2xl border border-[#d4ce9a] bg-[#f5f0c0] p-4 text-sm dark:border-[#4a4742] dark:bg-[#2e2c29]"><p className="mb-2 font-semibold">You asked</p><p className="text-[#5c5648] dark:text-[#c3bdad]">{question}</p><p className="mt-3 text-[#8c8470] dark:text-[#a7a08f]">I&apos;ll help you explore that. Ask another follow-up anytime.</p></div>)}
              </section>

              <form onSubmit={submitFollowUp} className="flex items-center gap-3 px-6">
                <div className="flex h-[50px] min-w-0 flex-1 items-center gap-2 rounded-full border border-[#d4ce9a] bg-[#fefae0] px-3 shadow-[0_4px_4px_rgba(23,23,23,.1),0_2px_2px_rgba(23,23,23,.06)] transition-colors focus-within:border-[#8c8470] dark:border-[#4a4742] dark:bg-[#2e2c29] dark:focus-within:border-[#8c8470]">
                  <PlusCircle size={22} className="shrink-0 text-[#8c8470]" />
                  <input aria-label="Ask a follow-up question" value={followUp} onChange={(e) => setFollowUp(e.target.value)} placeholder="Ask a follow up..." className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[#8c8470]" />
                  {followUp && <button type="button" aria-label="Clear follow-up" onClick={() => setFollowUp('')} className="text-[#8c8470] hover:text-[#252422]"><X size={18} /></button>}
                </div>
                <button aria-label="Send follow-up" type="submit" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#e97600] text-white shadow-sm transition hover:bg-[#cb6400] active:scale-95"><ArrowUp size={23} strokeWidth={2.4} /></button>
              </form>
            </article>
          </div>
          <button aria-label="Get help" onClick={() => notify('Ask-UTD help is coming soon')} className="absolute bottom-6 right-6 z-10 flex size-12 items-center justify-center rounded-full bg-[#e97600] text-white shadow-[0_12px_16px_-4px_rgba(16,24,40,.08),0_4px_6px_-2px_rgba(16,24,40,.03)] transition hover:scale-105 hover:bg-[#cb6400]"><CircleHelp size={23} strokeWidth={2.2} /></button>
          {toast && <div role="status" className="toast-message absolute bottom-7 left-1/2 z-40 -translate-x-1/2 rounded-xl bg-[#252422] px-4 py-2 text-sm font-medium text-white shadow-lg dark:bg-[#fefae0] dark:text-[#252422]">{toast}</div>}
        </section>
      </div>
    </main>
  );
}
