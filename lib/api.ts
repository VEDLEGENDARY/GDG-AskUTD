export type Citation = {
  n: number; chunk_id: string; doc_id: string; title: string;
  section: string; snippet: string; source_url: string | null;
};
export type Turn = { role: 'user' | 'assistant'; content: string };
export type StreamUpdate = {
  requestId?: string; text?: string; citations?: Citation[]; abstained?: boolean;
};

export async function apiError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(body?.error?.message || `The request failed (${response.status}). Please try again.`);
}

export async function streamAnswer(
  question: string, history: Turn[], onUpdate: (update: StreamUpdate) => void,
): Promise<void> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history: history.slice(-6), top_k: 5 }),
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok) throw await apiError(response);
  if (!response.body) throw new Error('The answer stream is unavailable. Please try again.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let done = false;
  function dispatch(frame: string) {
    const lines = frame.split('\n');
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
    const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    const payload = JSON.parse(data);
    if (event === 'error') throw new Error(payload.message || 'The answer could not be completed. Please retry.');
    if (event === 'meta') onUpdate({ requestId: payload.request_id });
    if (event === 'token') onUpdate({ text: payload.text });
    // A later citations event replaces the provisional retrieval citations.
    if (event === 'citations') onUpdate({ citations: payload });
    if (event === 'done') { done = true; onUpdate({ abstained: payload.abstained }); }
  }
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      buffer = buffer.replace(/\r\n/g, '\n');
      let end: number;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
      if (chunk.done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    if (!done) throw new Error('The connection ended before the answer finished. Please retry.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function sendFeedback(requestId: string, rating: 'up' | 'down'): Promise<void> {
  const response = await fetch('/api/feedback', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, rating }), signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw await apiError(response);
}
