import { useEffect, useMemo, useState } from 'react';
import { Bell, CheckCircle2, DollarSign, Play, Trophy, X, XCircle } from 'lucide-react';
import { useNotifications, type NotificationItem, type Toast } from '../lib/notifications';
import { usd } from '../lib/format';

const GAIN = 'var(--gain)';
const AMBER = '#fbbf24'; // sells are yellow, buys are green

interface Look { color: string; bg: string }
function lookFor(item: NotificationItem): Look {
  switch (item.kind) {
    case 'trade': return item.data?.side === 'buy' ? { color: GAIN, bg: 'rgba(16,217,160,0.14)' } : { color: AMBER, bg: 'rgba(251,191,36,0.14)' };
    case 'dividend': return { color: GAIN, bg: 'rgba(16,217,160,0.14)' };
    case 'tournament_start': return { color: 'var(--primary)', bg: 'rgba(0,200,255,0.14)' };
    case 'tournament_end': return { color: 'var(--accent)', bg: 'rgba(155,111,255,0.14)' };
    case 'game_win': return { color: AMBER, bg: 'rgba(251,191,36,0.14)' };
    case 'order_cancelled': return { color: 'var(--loss)', bg: 'rgba(255,61,92,0.12)' };
    default: return { color: 'var(--muted-foreground)', bg: 'rgba(255,255,255,0.06)' };
  }
}

function KindIcon({ kind, color }: { kind: string; color: string }) {
  const cls = 'w-4 h-4';
  const style = { color };
  switch (kind) {
    case 'dividend': return <DollarSign className={cls} style={style} />;
    case 'tournament_start': return <Play className={cls} style={style} />;
    case 'tournament_end': return <CheckCircle2 className={cls} style={style} />;
    case 'game_win': return <Trophy className={cls} style={style} />;
    case 'order_cancelled': return <XCircle className={cls} style={style} />;
    default: return <Bell className={cls} style={style} />;
  }
}

/** BUY (green) / SELL (yellow) pill, or an icon tile for every other kind. */
function Badge({ item }: { item: NotificationItem }) {
  const look = lookFor(item);
  if (item.kind === 'trade') {
    const buy = item.data?.side === 'buy';
    return (
      <span className="font-mono font-bold rounded-lg text-center shrink-0" style={{ fontSize: 10.5, width: 46, padding: '4px 0', background: look.bg, color: look.color, letterSpacing: '0.04em' }}>
        {buy ? 'BUY' : 'SELL'}
      </span>
    );
  }
  return (
    <span className="rounded-lg flex items-center justify-center shrink-0" style={{ width: 30, height: 30, background: look.bg }}>
      <KindIcon kind={item.kind} color={look.color} />
    </span>
  );
}

function tradeLine(item: NotificationItem): { head: string; sub: string } {
  const d = item.data ?? {};
  const q = Number(d.quantity ?? 0);
  return { head: String(d.player_name ?? 'Player'), sub: `${q.toLocaleString()} share${q === 1 ? '' : 's'} for ${usd(Number(d.total ?? 0))}` };
}

function ToastCard({ toast, onClose, onOpen }: { toast: Toast; onClose: () => void; onOpen: () => void }) {
  const { item } = toast;
  const look = lookFor(item);
  const trade = item.kind === 'trade' ? tradeLine(item) : null;
  return (
    <div
      className={`pointer-events-auto rounded-2xl border flex items-start gap-3 pl-3 pr-2 py-3 cursor-pointer ${toast.leaving ? 'toast-out' : 'toast-in'}`}
      style={{ background: 'var(--popover)', borderColor: look.color, boxShadow: '0 10px 32px rgba(0,0,0,0.45)', borderLeftWidth: 4 }}
      onClick={onOpen}
      role="status"
    >
      <Badge item={item} />
      <div className="min-w-0 flex-1">
        <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{trade ? trade.head : item.title}</p>
        <p className="text-muted-foreground" style={{ fontSize: 12.5, lineHeight: 1.4 }}>{trade ? trade.sub : item.body}</p>
      </div>
      <button onClick={e => { e.stopPropagation(); onClose(); }} aria-label="Dismiss" className="p-1 rounded-lg text-muted-foreground hover:bg-white/5 shrink-0">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

/** The pop-ups: top right, each slides in, waits, and slides back out. */
export function ToastStack({ onOpenInbox }: { onOpenInbox: () => void }) {
  const { toasts, dismissToast } = useNotifications();
  if (toasts.length === 0) return null;
  return (
    <div
      className="fixed z-[120] flex flex-col gap-2 pointer-events-none"
      style={{ top: 'max(14px, env(safe-area-inset-top))', right: 'max(14px, env(safe-area-inset-right))', width: 'min(360px, calc(100vw - 28px))' }}
      aria-live="polite"
    >
      {toasts.map(t => <ToastCard key={t.key} toast={t} onClose={() => dismissToast(t.key)} onOpen={() => { dismissToast(t.key); onOpenInbox(); }} />)}
    </div>
  );
}

/** Bell with a red dot while anything is unread (used in the phone top bar; the sidebar draws its own). */
export function BellButton({ onClick }: { onClick: () => void }) {
  const { unread } = useNotifications();
  return (
    <button onClick={onClick} aria-label={unread > 0 ? 'Notifications (unread)' : 'Notifications'} className="relative p-2.5 rounded-xl hover:bg-white/5 text-foreground">
      <Bell className="w-5 h-5" />
      {unread > 0 && <span className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full" style={{ background: '#ff3d5c', boxShadow: '0 0 0 2px var(--sidebar)' }} />}
    </button>
  );
}

function ago(iso: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function dayLabel(iso: string | null): string {
  if (!iso) return 'Earlier';
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

/** The notifications page. Opening it reads everything; the ones that were unread stay highlighted until you leave. */
export function NotificationsPage() {
  const { items, openInbox } = useNotifications();
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    void openInbox().then(ids => { if (alive) { setFresh(ids); setLoaded(true); } });
    return () => { alive = false; };
  }, [openInbox]);

  const groups = useMemo(() => {
    const out: { label: string; rows: NotificationItem[] }[] = [];
    for (const it of items) {
      const label = dayLabel(it.created_at);
      const last = out[out.length - 1];
      if (last && last.label === label) last.rows.push(it); else out.push({ label, rows: [it] });
    }
    return out;
  }, [items]);

  return (
    <div className="p-6 page-pad max-w-[760px] mx-auto space-y-5">
      <div>
        <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Notifications</h1>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Your trades, cancelled orders, dividends, and the tournaments and wins that matter to the players you own.
        </p>
      </div>

      {!loaded && items.length === 0 ? (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading…</p>
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-border p-10 text-center" style={{ background: 'var(--card)' }}>
          <Bell className="w-7 h-7 mx-auto mb-3 text-muted-foreground" />
          <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>Nothing yet</p>
          <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>Trades, dividends and tournament updates will show up here.</p>
        </div>
      ) : (
        groups.map(g => (
          <div key={g.label}>
            <p className="text-muted-foreground font-semibold mb-2 px-1" style={{ fontSize: 12, letterSpacing: '0.04em' }}>{g.label.toUpperCase()}</p>
            <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
              {g.rows.map((it, i) => {
                const isNew = fresh.has(it.id);
                const trade = it.kind === 'trade' ? tradeLine(it) : null;
                return (
                  <div key={it.id} className="flex items-start gap-3 px-4 py-3" style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border)', background: isNew ? 'rgba(0,200,255,0.06)' : undefined }}>
                    <Badge item={it} />
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground font-semibold" style={{ fontSize: 13.5 }}>{trade ? `${it.data?.side === 'buy' ? 'Bought' : 'Sold'} ${trade.head}` : it.title}</p>
                      <p className="text-muted-foreground" style={{ fontSize: 12.5, lineHeight: 1.45 }}>{trade ? trade.sub : it.body}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className="text-muted-foreground font-mono" style={{ fontSize: 11 }}>{ago(it.created_at)}</span>
                      {isNew && <span className="rounded-full" style={{ width: 7, height: 7, background: 'var(--primary)' }} aria-label="New" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
