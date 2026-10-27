import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import { toNumber, type ActivityItem, type ActivityPage } from '../lib/types';

const TABS = [
  { key: 'all', label: 'All' },
  { key: 'trades', label: 'Buys & sells' },
  { key: 'dividends', label: 'Dividends' },
  { key: 'fees', label: 'Fees' },
  { key: 'treasury', label: 'Treasury' },
  { key: 'cash', label: 'Deposits' },
] as const;
type TabKey = (typeof TABS)[number]['key'];

const PAGE = 25;

const BADGE: Record<string, { label: string; color: string; bg: string }> = {
  buy: { label: 'BUY', color: 'var(--gain)', bg: 'rgba(16,217,160,0.12)' },
  sell: { label: 'SELL', color: '#ffb020', bg: 'rgba(255,176,32,0.12)' },
  dividend: { label: 'DIVIDEND', color: '#9b6fff', bg: 'rgba(155,111,255,0.14)' },
  fee: { label: 'FEE', color: 'var(--loss)', bg: 'rgba(255,61,92,0.12)' },
  treasury_buy: { label: 'TREASURY', color: 'var(--primary)', bg: 'rgba(0,200,255,0.12)' },
  treasury_redeem: { label: 'TREASURY', color: 'var(--primary)', bg: 'rgba(0,200,255,0.12)' },
  deposit: { label: 'DEPOSIT', color: 'var(--muted-foreground)', bg: 'rgba(255,255,255,0.07)' },
  withdrawal: { label: 'WITHDRAWAL', color: 'var(--muted-foreground)', bg: 'rgba(255,255,255,0.07)' },
};

const money = (v: number) => `${v < 0 ? '-' : '+'}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** The account's full activity: every buy and sell, dividend payout, fee, treasury move and deposit, newest first,
 * with the cash balance after each. Comes from the wallet ledger (GET /wallet/activity), so it always adds up. */
export function ActivityHistory({ openPlayer }: { openPlayer: (id: string) => void }) {
  const [tab, setTab] = useState<TabKey>('all');
  const [data, setData] = useState<{ items: ActivityItem[]; total: number; next: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const fetchPage = useCallback((kind: TabKey, offset: number) =>
    api.get<ActivityPage>(`/wallet/activity?kind=${kind}&limit=${PAGE}&offset=${offset}`), []);

  // (Re)load the first page whenever the tab changes, and refresh it quietly every 30s so new trades appear.
  // Once the user has pressed "Load more", the quiet refresh only updates the total so their list doesn't jump.
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    const load = () =>
      fetchPage(tab, 0)
        .then(r => {
          if (cancelled) return;
          setData(prev => (prev && prev.items.length > PAGE
            ? { ...prev, total: r.total }
            : { items: r.items, total: r.total, next: r.next_offset }));
        })
        .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load activity'); });
    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [tab, fetchPage]);

  const loadMore = () => {
    if (!data || data.next === null || loadingMore) return;
    const offset = data.next;
    setLoadingMore(true);
    fetchPage(tab, offset)
      .then(r => setData(prev => (prev ? { items: [...prev.items, ...r.items], total: r.total, next: r.next_offset } : prev)))
      .catch(e => setError(e instanceof Error ? e.message : 'Could not load more'))
      .finally(() => setLoadingMore(false));
  };

  const items = data?.items ?? null;
  const total = data?.total ?? 0;
  const nextOffset = data?.next ?? null;

  return (
    <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
      <div className="px-5 py-4 border-b border-border">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p className="text-foreground font-semibold" style={{ fontSize: 16 }}>Activity</p>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>Your buys, sells, dividend payouts and fees, newest first</p>
          </div>
          {items !== null && <p className="text-muted-foreground" style={{ fontSize: 12 }}>{total.toLocaleString()} entr{total === 1 ? 'y' : 'ies'}</p>}
        </div>
        <div className="flex gap-1 mt-3 flex-wrap">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="rounded-lg font-semibold transition-colors"
              style={{
                fontSize: 12, padding: '4px 10px',
                background: tab === t.key ? 'rgba(0,200,255,0.12)' : 'transparent',
                color: tab === t.key ? 'var(--primary)' : 'var(--muted-foreground)',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="px-5 py-3" style={{ fontSize: 13, color: 'var(--loss)' }}>{error}</p>}

      {items === null && !error ? (
        <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading…</p>
      ) : items !== null && items.length === 0 ? (
        <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>
          Nothing here yet. Your trades and dividend payouts will show up as they happen.
        </p>
      ) : (
        <div>
          {(items ?? []).map((it, i) => {
            const b = BADGE[it.type] ?? { label: it.type.toUpperCase(), color: 'var(--muted-foreground)', bg: 'rgba(255,255,255,0.07)' };
            const amount = toNumber(it.amount);
            const clickable = !!it.player_id;
            return (
              <div
                key={it.id}
                onClick={clickable ? () => openPlayer(it.player_id as string) : undefined}
                className={`flex items-center gap-3 px-5 py-3 ${clickable ? 'cursor-pointer hover:bg-white/[0.03]' : ''}`}
                style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}
              >
                <span className="font-mono font-bold rounded-lg text-center shrink-0" style={{ fontSize: 10, width: 74, padding: '3px 0', background: b.bg, color: b.color }}>
                  {b.label}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-foreground font-medium truncate" style={{ fontSize: 14 }}>{it.title}</p>
                  <p className="text-muted-foreground truncate" style={{ fontSize: 11.5 }}>
                    {when(it.at)}{it.detail ? ` · ${it.detail}` : ''}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono font-bold" style={{ fontSize: 14, color: amount >= 0 ? 'var(--gain)' : 'var(--foreground)' }}>{money(amount)}</p>
                  <p className="text-muted-foreground font-mono" style={{ fontSize: 10.5 }}>
                    bal ${toNumber(it.balance_after).toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  </p>
                </div>
              </div>
            );
          })}
          {nextOffset !== null && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="w-full py-3 text-primary font-medium hover:bg-white/[0.03] transition-colors"
              style={{ fontSize: 13, borderTop: '1px solid var(--border)' }}
            >
              {loadingMore ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
