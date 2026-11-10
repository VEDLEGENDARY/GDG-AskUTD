import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { streamAnswer, sendFeedback } from '../lib/api.ts';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
function stream(chunks) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({ start(controller) {
    for (const part of chunks) controller.enqueue(encoder.encode(part));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}
test('stream handles split frames, UTF-8, final citation replacement and history limit', async () => {
  let body;
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(options.body);
    return stream(['event: meta\r\ndata: {"request_id":"r1"}\r\n\r',
      '\nevent: citations\ndata: [{"n":1}]\n\nevent: tok',
      'en\ndata: {"text":"Café [1]"}\n\nevent: citations\ndata: []\n\n',
      'event: done\ndata: {"abstained":false}\n\n']);
  };
  const updates = [];
  await streamAnswer('drop a class', Array(8).fill({ role: 'user', content: 'prior question' }), (v) => updates.push(v));
  assert.equal(body.history.length, 6);
  assert.equal(body.question, 'drop a class');
  assert.deepEqual(updates, [{ requestId: 'r1' }, { citations: [{ n: 1 }] },
    { text: 'Café [1]' }, { citations: [] }, { abstained: false }]);
});
test('HTTP errors and SSE errors are shown instead of success', async () => {
  globalThis.fetch = async () => new Response('{"error":{"message":"Too many requests"}}', { status: 429 });
  await assert.rejects(streamAnswer('q', [], () => {}), /Too many requests/);
  globalThis.fetch = async () => stream(['event: error\ndata: {"message":"Model unavailable"}\n\n']);
  await assert.rejects(streamAnswer('q', [], () => {}), /Model unavailable/);
});
test('disconnected stream cannot be mistaken for a completed answer', async () => {
  globalThis.fetch = async () => stream(['event: token\ndata: {"text":"partial"}\n\n']);
  await assert.rejects(streamAnswer('q', [], () => {}), /before the answer finished/);
});
test('feedback uses the stored request id and handles rejection', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/feedback');
    assert.deepEqual(JSON.parse(options.body), { request_id: 'r1', rating: 'up' });
    return new Response(null, { status: 204 });
  };
  await sendFeedback('r1', 'up');
  globalThis.fetch = async () => new Response('unavailable', { status: 503 });
  await assert.rejects(sendFeedback('r1', 'up'), /503/);
});
