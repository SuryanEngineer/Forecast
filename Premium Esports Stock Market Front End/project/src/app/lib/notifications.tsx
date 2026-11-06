import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api } from './api';
import { useAuth } from './auth';

// In-app notifications (trades, cancelled orders, dividends, tournaments, game wins). The server writes one row per
// event; this provider is the other half of the "read" rules:
//   * on the site (tab visible): anything NEW pops up as a toast and is marked read straight away;
//   * away (tab hidden / closed): it stays unread -> red dot on the bell, no pop-up when you come back;
//   * opening the notifications page reads everything at once.
// "New" is decided by what this tab has already seen, not by clocks, so a skewed device clock can't break it.

export interface NotificationItem {
  id: string;
  kind: 'trade' | 'order_cancelled' | 'dividend' | 'tournament_start' | 'tournament_end' | 'game_win' | string;
  title: string;
  body: string;
  data: Record<string, any>;
  created_at: string | null;
  read: boolean;
}

export interface Toast { key: string; item: NotificationItem; leaving: boolean }

interface Ctx {
  items: NotificationItem[];
  unread: number;
  toasts: Toast[];
  dismissToast: (key: string) => void;
  /** Called when the notifications page opens: loads the list, reads everything, and returns which ones were unread. */
  openInbox: () => Promise<Set<string>>;
}

const EMPTY: Ctx = { items: [], unread: 0, toasts: [], dismissToast: () => {}, openInbox: async () => new Set() };
const NotificationsContext = createContext<Ctx>(EMPTY);

export const useNotifications = () => useContext(NotificationsContext);

const POLL_MS = 7_000;
const TOAST_MS = 6_500;
const MAX_TOASTS = 4;
const LIMIT = 60;

interface ListResponse { items: NotificationItem[]; unread: number }

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { wallet } = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const known = useRef<Set<string>>(new Set());
  const primed = useRef(false);
  const busy = useRef(false);

  const dismissToast = useCallback((key: string) => {
    setToasts(t => t.map(x => (x.key === key ? { ...x, leaving: true } : x)));
    setTimeout(() => setToasts(t => t.filter(x => x.key !== key)), 320);
  }, []);

  const showToasts = useCallback((fresh: NotificationItem[]) => {
    // Several at once cascade in rather than landing on top of each other.
    fresh.slice(0, MAX_TOASTS).forEach((item, i) => {
      setTimeout(() => {
        setToasts(t => [...t.filter(x => !x.leaving).slice(-(MAX_TOASTS - 1)), { key: item.id, item, leaving: false }]);
        setTimeout(() => dismissToast(item.id), TOAST_MS);
      }, i * 550);
    });
  }, [dismissToast]);

  const markRead = useCallback(async (ids: string[] | null) => {
    try { await api.post('/notifications/read', ids ? { ids } : {}); } catch { /* the next poll will retry what is still unread */ }
  }, []);

  const refresh = useCallback(async () => {
    if (document.visibilityState !== 'visible' || busy.current) return;
    busy.current = true;
    try {
      const r = await api.get<ListResponse>(`/notifications?limit=${LIMIT}`);
      if (!primed.current) {
        // First look after loading / coming back to the tab: whatever is unread arrived while away. It stays unread.
        primed.current = true;
        known.current = new Set(r.items.map(i => i.id));
        setItems(r.items);
        setUnread(r.unread);
        return;
      }
      const fresh = r.items.filter(i => !known.current.has(i.id));
      fresh.forEach(i => known.current.add(i.id));
      const freshUnread = fresh.filter(i => !i.read);
      if (freshUnread.length > 0) {
        // On the site: show it, and it counts as read straight away.
        showToasts([...freshUnread].reverse());
        void markRead(freshUnread.map(i => i.id));
      }
      const freshUnreadIds = new Set(freshUnread.map(i => i.id));
      setItems(r.items.map(i => (freshUnreadIds.has(i.id) ? { ...i, read: true } : i)));
      setUnread(Math.max(0, r.unread - freshUnread.length));
    } catch { /* offline / signed out: try again next tick */ }
    finally { busy.current = false; }
  }, [markRead, showToasts]);

  // Poll while the tab is visible; treat coming back to the tab as "was away" (re-prime).
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    const onVis = () => {
      if (document.visibilityState === 'visible') { primed.current = false; void refresh(); }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [refresh]);

  // Cash or reserved cash just changed (a quick order, a fill, a cancel): look straight away instead of waiting for the poll.
  const walletKey = wallet ? `${wallet.cash_balance}|${wallet.held_balance}` : '';
  useEffect(() => {
    if (!walletKey) return;
    const t = setTimeout(() => void refresh(), 700);
    return () => clearTimeout(t);
  }, [walletKey, refresh]);

  const openInbox = useCallback(async () => {
    try {
      const r = await api.get<ListResponse>(`/notifications?limit=${LIMIT}`);
      const wasUnread = new Set(r.items.filter(i => !i.read).map(i => i.id));
      r.items.forEach(i => known.current.add(i.id));
      primed.current = true;
      setItems(r.items.map(i => ({ ...i, read: true })));
      setUnread(0);
      if (r.unread > 0) await markRead(null);
      return wasUnread;
    } catch {
      return new Set<string>();
    }
  }, [markRead]);

  const value = useMemo(() => ({ items, unread, toasts, dismissToast, openInbox }), [items, unread, toasts, dismissToast, openInbox]);
  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}
