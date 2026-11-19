// Thin fetch wrapper around the forecast-backend REST API.
//
// Base URL comes from VITE_API_BASE_URL (see .env.example) and defaults
// to the local dev server address documented in
// forecast-backend/README_SETUP.md (`uvicorn app.main:app --reload`,
// served at http://localhost:8000).
//
// The auth token is kept in localStorage (this is a real standalone app
// the user runs in their own browser -- not a sandboxed Claude artifact
// -- so localStorage is the normal, correct place for a JWT in a SPA).

const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
const TOKEN_KEY = 'forecast_access_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

// Last good response per GET path, so a page you have already seen paints instantly while it refreshes in the
// background (see usePolledFetch). It is kept in localStorage too (shared by every tab and kept between visits), so even
// opening the site tomorrow paints from it straight away while fresh data loads. It is tied to the signed-in account (a
// tag of the token) and wiped whenever the account changes, so one account's data can never show up for another.
interface CacheEntry { data: unknown; at: number }
const CACHE_KEY = 'forecast_response_cache_v2';
const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const CACHE_ENTRY_MAX_CHARS = 400_000;
const CACHE_TOTAL_MAX_CHARS = 3_000_000;
const cacheMem = new Map<string, CacheEntry>();
let cacheHydrated = false;
let persistTimer: ReturnType<typeof setTimeout> | null = null;

const tokenTag = () => (getToken() ?? 'guest').slice(-16);

function hydrateCache() {
  if (cacheHydrated) return;
  cacheHydrated = true;
  try {
    try { localStorage.removeItem('forecast_response_cache_v1'); } catch { /* old session-scoped cache */ }
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return;
    const blob = JSON.parse(raw) as { tag: string; entries: Record<string, CacheEntry> };
    if (blob.tag !== tokenTag()) { localStorage.removeItem(CACHE_KEY); return; }
    const now = Date.now();
    for (const [k, e] of Object.entries(blob.entries)) if (now - e.at < CACHE_MAX_AGE_MS) cacheMem.set(k, e);
  } catch { /* unreadable cache: start empty */ }
}

function schedulePersist() {
  if (persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    try {
      const entries: Record<string, CacheEntry> = {};
      let total = 0;
      // Newest first, until the budget runs out.
      for (const [k, e] of [...cacheMem.entries()].sort((a, b) => b[1].at - a[1].at)) {
        const size = JSON.stringify(e.data).length;
        if (size > CACHE_ENTRY_MAX_CHARS || total + size > CACHE_TOTAL_MAX_CHARS) continue;
        entries[k] = e; total += size;
      }
      localStorage.setItem(CACHE_KEY, JSON.stringify({ tag: tokenTag(), entries }));
    } catch { /* storage full or unavailable: the in-memory cache still works */ }
  }, 1000);
}

export const responseCache = {
  get(path: string): unknown | undefined { hydrateCache(); return cacheMem.get(path)?.data; },
  /** Milliseconds since this path was last fetched, or Infinity if never. */
  age(path: string): number { hydrateCache(); const e = cacheMem.get(path); return e ? Date.now() - e.at : Infinity; },
  set(path: string, data: unknown): void { hydrateCache(); cacheMem.set(path, { data, at: Date.now() }); schedulePersist(); },
  clear(): void {
    cacheMem.clear();
    cacheHydrated = true;
    try { localStorage.removeItem(CACHE_KEY); } catch { /* ignore */ }
  },
};

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  responseCache.clear();
}

/** Wakes the server up. The free host puts an idle backend to sleep, and the first request after that can take 30+
 * seconds; pinging it the moment the page opens means it is usually awake by the time anyone clicks anything. */
export function warmUpBackend(): void {
  try {
    const root = API_BASE_URL.replace(/\/api\/v1\/?$/, '');
    // /health answers instantly on an awake server, so if it has not answered after a few seconds the server is waking
    // from sleep: tell the page (see ServerWakingBanner) so people see why things are slow instead of a blank screen.
    const timer = window.setTimeout(() => setWaking(true), 4000);
    const done = () => { window.clearTimeout(timer); setWaking(false); };
    void fetch(`${root}/health`, { method: 'GET', mode: 'no-cors', cache: 'no-store' }).then(done, done);
  } catch { /* best effort */ }
}

let waking = false;
const wakingListeners = new Set<(waking: boolean) => void>();
function setWaking(value: boolean): void {
  if (waking === value) return;
  waking = value;
  wakingListeners.forEach(listener => listener(value));
}
/** Calls `listener` now and whenever the "server is waking up" state changes. Returns an unsubscribe function. */
export function subscribeWaking(listener: (waking: boolean) => void): () => void {
  wakingListeners.add(listener);
  listener(waking);
  return () => { wakingListeners.delete(listener); };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---- GET politeness: a small queue + retries ----------------------------------------------------------------------
// The backend has ~11 database connections. A page that fires 10+ requests at once (plus the polling) used to queue them
// all server-side and time out; now at most MAX_GETS run at a time and the rest wait here (first asked, first served).
// A GET that fails because the server is waking up (network error, 502/503/504, or a hung request) is retried with a
// growing pause, and the "server is waking" banner shows meanwhile. POSTs are never retried (they could double-execute).
const MAX_GETS = 5;
const GET_TIMEOUT_MS = 40_000;
const RETRY_PAUSES_MS = [1500, 4000, 8000];
let activeGets = 0;
const getQueue: Array<() => void> = [];

function acquireGetSlot(): Promise<void> {
  if (activeGets < MAX_GETS) { activeGets++; return Promise.resolve(); }
  return new Promise(resolve => getQueue.push(() => { activeGets++; resolve(); }));
}
function releaseGetSlot(): void {
  activeGets--;
  const next = getQueue.shift();
  if (next) next();
}
const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

async function fetchOnce(url: string, options: RequestInit, timeoutMs: number | null): Promise<Response> {
  if (timeoutMs === null) return fetch(url, options);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try { return await fetch(url, { ...options, signal: ctl.signal }); }
  finally { clearTimeout(timer); }
}

async function fetchWithRetry(url: string, options: RequestInit): Promise<Response> {
  const isGet = (options.method ?? 'GET') === 'GET';
  if (!isGet) return fetch(url, options);
  await acquireGetSlot();
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await fetchOnce(url, options, GET_TIMEOUT_MS);
        if ((res.status === 502 || res.status === 503 || res.status === 504) && attempt < RETRY_PAUSES_MS.length) {
          setWaking(true);
          await sleep(RETRY_PAUSES_MS[attempt]);
          continue;
        }
        if (res.status < 500) setWaking(false);
        return res;
      } catch (err) {
        if (attempt >= RETRY_PAUSES_MS.length) throw err;
        setWaking(true);
        await sleep(RETRY_PAUSES_MS[attempt]);
      }
    }
  } finally {
    releaseGetSlot();
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetchWithRetry(`${API_BASE_URL}${path}`, { ...options, headers });

  if (res.status === 204) return undefined as T;

  const isJson = res.headers.get('content-type')?.includes('application/json');
  const body = isJson ? await res.json().catch(() => null) : null;

  if (res.status === 401 && token && !path.startsWith('/auth/login')) {
    // Token expired or revoked (e.g. password changed on another device): drop it and tell the app to sign out.
    setToken(null);
    window.dispatchEvent(new Event('forecast:unauthorized'));
  }

  if (!res.ok) {
    const message = (body && (body.detail || body.message)) || res.statusText || 'Request failed';
    throw new ApiError(res.status, typeof message === 'string' ? message : JSON.stringify(message));
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data !== undefined ? JSON.stringify(data) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export { API_BASE_URL };
