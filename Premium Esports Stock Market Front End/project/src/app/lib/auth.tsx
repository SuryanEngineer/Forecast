import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, getToken, setToken as persistToken, ApiError } from './api';
import type { AuthUser, WalletResponse } from './types';

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: AuthUser | null;
  wallet: WalletResponse | null;
  error: string | null;
  // True only for the AuthenticatedApp mount that immediately follows a
  // successful register() call -- lets App.tsx auto-show IntroTour on a
  // brand new account without also re-showing it to a returning user who
  // simply logs in again on a new device/browser (see IntroTour.tsx's
  // storageKey mechanism for the "already seen it" side of that, which
  // this flag is deliberately independent from). Reset on every login()
  // and logout() so it never lingers past the registration it belongs to.
  justRegistered: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string, acceptTerms: boolean) => Promise<void>;
  logout: () => void;
  refreshWallet: () => Promise<void>;
  requestPasswordReset: (email: string) => Promise<string>;
  confirmPasswordReset: (email: string, code: string, newPassword: string) => Promise<string>;
  // Re-fetch /auth/me (after a profile/email change). Optionally adopt a fresh token (after a password change).
  refreshUser: (newToken?: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [wallet, setWallet] = useState<WalletResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [justRegistered, setJustRegistered] = useState(false);

  async function refreshWallet() {
    try {
      const w = await api.get<WalletResponse>('/wallet/me');
      setWallet(w);
    } catch {
      // Not fatal -- the balance just won't show until the next successful fetch.
    }
  }

  async function loadSession() {
    const me = await api.get<AuthUser>('/auth/me');
    setUser(me);
    await refreshWallet();
  }

  // On load, if a token is already stored (from a previous session),
  // treat it as authenticated optimistically and confirm by fetching the
  // profile. If that fails (expired/invalid token), log out cleanly.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setIsLoading(false);
      return;
    }
    loadSession()
      .catch(() => persistToken(null))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setWallet(null);
    };
    window.addEventListener('forecast:unauthorized', onUnauthorized);
    return () => window.removeEventListener('forecast:unauthorized', onUnauthorized);
  }, []);

  async function login(email: string, password: string) {
    setError(null);
    try {
      const res = await api.post<{ access_token: string; user_id: string }>('/auth/login', { email, password });
      persistToken(res.access_token);
      setJustRegistered(false);
      await loadSession();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Login failed');
      throw e;
    }
  }

  async function register(email: string, password: string, displayName: string, acceptTerms: boolean) {
    setError(null);
    try {
      const res = await api.post<{ access_token: string; user_id: string }>('/auth/register', {
        email,
        password,
        display_name: displayName,
        accept_terms: acceptTerms,
      });
      persistToken(res.access_token);
      setJustRegistered(true);
      await loadSession();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Registration failed');
      throw e;
    }
  }

  function logout() {
    persistToken(null);
    setUser(null);
    setWallet(null);
    setJustRegistered(false);
  }

  // Both of these return the backend's user-facing message string (see
  // MessageResponse in app/schemas/auth.py) rather than throwing on the
  // "success" path, since the request-reset endpoint always reports
  // success by design (see app/services/password_reset_service.py) --
  // there's no separate "did it actually find an account" state to
  // surface here even if we wanted to.
  async function requestPasswordReset(email: string): Promise<string> {
    setError(null);
    try {
      const res = await api.post<{ message: string }>('/auth/password-reset/request', { email });
      return res.message;
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Could not request a password reset right now.';
      setError(message);
      throw e;
    }
  }

  async function confirmPasswordReset(email: string, code: string, newPassword: string): Promise<string> {
    setError(null);
    try {
      const res = await api.post<{ message: string }>('/auth/password-reset/confirm', {
        email,
        code,
        new_password: newPassword,
      });
      return res.message;
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'That code is invalid or has expired.';
      setError(message);
      throw e;
    }
  }

  async function refreshUser(newToken?: string) {
    if (newToken) persistToken(newToken);
    try {
      setUser(await api.get<AuthUser>('/auth/me'));
    } catch {
      // ignore -- a 401 here is handled by the next real request
    }
  }

  // Activity heartbeat (powers session / time-on-site analytics). Ticks once a minute, only while the tab is
  // visible; also fires immediately when the user returns to the tab. Any 401 simply means the token is gone.
  useEffect(() => {
    if (!user) return;
    let last = 0;
    const beat = () => {
      if (document.visibilityState !== 'visible') return;
      const now = Date.now();
      if (now - last < 45_000) return;
      last = now;
      api.post('/auth/heartbeat').catch(() => {});
    };
    beat();
    const id = setInterval(beat, 60_000);
    document.addEventListener('visibilitychange', beat);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', beat);
    };
  }, [user?.id]);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!user,
        isLoading,
        user,
        wallet,
        error,
        justRegistered,
        login,
        register,
        logout,
        refreshWallet,
        requestPasswordReset,
        confirmPasswordReset,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
