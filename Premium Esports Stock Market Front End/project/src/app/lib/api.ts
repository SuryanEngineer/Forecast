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

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
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
