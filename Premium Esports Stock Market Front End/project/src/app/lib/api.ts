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
// background (see usePolledFetch). It is kept in this tab's sessionStorage too, so even a full browser reload paints
// from it. It is tied to the signed-in account (a tag of the token) and wiped whenever the account changes, so one
// account's data can never show up for another.
interface CacheEntry { data: unknown; at: number }
const CACHE_KEY = 'forecast_response_cache_v1';
const CACHE_MAX_AGE_MS = 60 * 60 * 1000;
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
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return;
    const blob = JSON.parse(raw) as { tag: string; entries: Record<string, CacheEntry> };
    if (blob.tag !== tokenTag()) { sessionStorage.removeItem(CACHE_KEY); return; }
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
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ tag: tokenTag(), entries }));
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
    try { sessionStorage.removeItem(CACHE_KEY); } catch { /* ignore */ }
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
    void fetch(`${root}/health`, { method: 'GET', mode: 'no-cors', cache: 'no-store' }).catch(() => {});
  } catch { /* best effort */ }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

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
