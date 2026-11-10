// Start the real API and Next.js together, with an offline answer provider by default.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const cwd = fileURLToPath(new URL('../', import.meta.url));
try { process.loadEnvFile(fileURLToPath(new URL('../.env', import.meta.url))); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const env = { ...process.env, LLM_PROVIDER: process.env.LLM_PROVIDER || 'extractive',
  USE_STUBS: process.env.USE_STUBS || '0', API_BASE_URL: 'http://127.0.0.1:8000' };
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (process.platform === 'win32' && child.pid) {
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    } else child.kill();
  }
  process.exitCode = code;
}
function run(command, args) {
  const child = spawn(command, args, { cwd, env, stdio: 'inherit', windowsHide: true });
  children.push(child);
  child.on('error', (error) => { console.error(error.message); stop(1); });
  child.on('exit', (code) => { if (!stopping) stop(code || 0); });
  return child;
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
run(process.env.PYTHON || (process.platform === 'win32' ? 'py' : 'python3'),
  ['-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000']);
let healthy = false;
for (let i = 0; i < 60 && !stopping; i++) {
  try {
    const response = await fetch('http://127.0.0.1:8000/api/health', { signal: AbortSignal.timeout(1000) });
    if (response.ok) { healthy = true; break; }
  } catch { /* API may still be starting. */ }
  await new Promise((resolve) => setTimeout(resolve, 500));
}
if (healthy && !stopping) run(process.execPath, ['node_modules/next/dist/bin/next', 'dev']);
else if (!stopping) { console.error('API did not become healthy. Install requirements-runtime.txt and check port 8000.'); stop(1); }
