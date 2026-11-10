import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { api, getToken } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useMarketsByIds } from '../lib/hooks';
import { toNumber, type OrderResponse } from '../lib/types';
import { usd } from '../lib/format';

// A resting limit order ties up cash (buys) or shares (sells) until it fills or is cancelled, so nobody should be able
// to leave one open by accident. Open orders are therefore shown in several places (My Portfolio, the player's own page, a
// banner on Home, a count on the sidebar), each with a one-tap Cancel and a "Cancel all". They stay in sync through a
// tiny window event: anything that places or cancels an order calls notifyOrdersChanged().
const ORDERS_CHANGED = 'forecast:orders-changed';
export function notifyOrdersChanged() {
  window.dispatchEvent(new Event(ORDERS_CHANGED));
}

/** The user's open / part-filled LIMIT orders (optionally for one player), refreshed every 15s and on notifyOrdersChanged(). */
export function useOpenOrders(playerId?: string): { orders: OrderResponse[] | null; reload: () => void } {
  const [orders, setOrders] = useState<OrderResponse[] | null>(null);
  const load = useCallback(() => {
    if (!getToken()) { setOrders([]); return; } // guest mode: no account, no orders
    api.get<OrderResponse[]>(playerId ? `/orders/me?player_id=${playerId}` : '/orders/me')
      .then(rows => setOrders(rows.filter(o => o.order_kind === 'limit' && (o.status === 'open' || o.status === 'partially_filled'))))
      .catch(() => setOrders(prev => prev ?? []));
  }, [playerId]);

  useEffect(() => {
    load();
    const id = setInterval(load, 15_000);
    window.addEventListener(ORDERS_CHANGED, load);
    return () => { clearInterval(id); window.removeEventListener(ORDERS_CHANGED, load); };
  }, [load]);

  return { orders, reload: load };
}

const AMBER = '#fbbf24';

function expiryText(expiresAt?: string | null): string {
  if (!expiresAt) return 'open until cancelled';
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return 'expiring now';
  const mins = Math.round(ms / 60_000);
  if (mins < 60) return `expires in ${Math.max(1, mins)}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `expires in ${hrs}h`;
  return `expires in ${Math.round(hrs / 24)}d`;
}

/** The open-orders list with Cancel on every row and Cancel all. Renders nothing when there are none.
 * `playerId` limits it to one player (used inside that player's page). */
export function OpenOrders({ openPlayer, playerId }: { openPlayer?: (id: string) => void; playerId?: string }) {
  const { refreshWallet } = useAuth();
  const { orders, reload } = useOpenOrders(playerId);
  const [busy, setBusy] = useState<string | 'all' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // order id whose price is being edited
  const [draft, setDraft] = useState('');

  const ids = useMemo(() => (orders ?? []).map(o => o.player_id), [orders]);
  const { data: markets } = useMarketsByIds(ids);

  async function cancelOne(id: string): Promise<boolean> {
    try {
      await api.post(`/orders/${id}/cancel`);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not cancel that order');
      return false;
    }
  }

  async function cancel(id: string) {
    setBusy(id); setError(null);
    await cancelOne(id);
    await finish();
  }

  async function savePrice(o: OrderResponse) {
    const price = parseFloat(draft);
    if (!Number.isFinite(price) || price <= 0) { setError('Enter a price above $0.'); return; }
    if (price === toNumber(o.limit_price ?? 0)) { setEditing(null); return; }
    setBusy(o.id); setError(null);
    try {
      await api.post(`/orders/${o.id}/price`, { price });
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that order’s price');
    }
    await finish();
  }

  async function cancelAll() {
    if (!orders) return;
    setBusy('all'); setError(null);
    for (const o of orders) await cancelOne(o.id);
    await finish();
  }

  async function finish() {
    await refreshWallet();
    notifyOrdersChanged(); // refreshes every other open-orders view (sidebar count, banner, ...)
    reload();
    setBusy(null);
  }

  if (!orders || orders.length === 0) return null;
  const many = orders.length > 1;
  const worth = (o: OrderResponse) => (o.quantity - o.filled_quantity) * toNumber(o.limit_price ?? 0);
  const buyTotal = orders.filter(o => o.side === 'buy').reduce((s, o) => s + worth(o), 0);
  const sellTotal = orders.filter(o => o.side === 'sell').reduce((s, o) => s + worth(o), 0);

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(251,191,36,0.06)', border: '1.5px solid rgba(251,191,36,0.55)' }}>
      <div className="px-5 py-3.5 flex items-start justify-between gap-3 flex-wrap" style={{ borderBottom: '1px solid rgba(251,191,36,0.25)' }}>
        <div className="flex items-start gap-2.5">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: AMBER }} />
          <div>
            <p className="text-foreground font-bold" style={{ fontSize: 15 }}>
              You have {orders.length} open order{many ? 's' : ''}
            </p>
            <p className="text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.45 }}>
              Open orders lock up your cash or shares and can fill later without you watching. Cancel any you no longer want.
            </p>
          </div>
        </div>
        {many && (
          <button
            onClick={cancelAll}
            disabled={busy !== null}
            className="px-3.5 py-2 rounded-lg font-bold transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ fontSize: 12.5, background: 'var(--loss)', color: '#fff' }}
          >
            {busy === 'all' ? 'Cancelling…' : `Cancel all ${orders.length}`}
          </button>
        )}
      </div>
      <div className="px-5 py-2.5 flex flex-wrap gap-x-6 gap-y-1 font-mono" style={{ fontSize: 12.5, borderBottom: '1px solid rgba(251,191,36,0.15)' }}>
        <span className="text-muted-foreground">Total buy orders <strong style={{ color: 'var(--gain)' }}>{usd(buyTotal)}</strong></span>
        <span className="text-muted-foreground">Total sell orders <strong style={{ color: '#ffb020' }}>{usd(sellTotal)}</strong></span>
      </div>
      {error && <p className="px-5 py-2" style={{ fontSize: 12.5, color: 'var(--loss)' }}>{error}</p>}
      {orders.map((o, i) => {
        const m = markets.get(o.player_id);
        const left = o.quantity - o.filled_quantity;
        const buy = o.side === 'buy';
        return (
          <div key={o.id} className="flex items-center gap-3 px-5 py-3" style={{ borderTop: i === 0 ? 'none' : '1px solid rgba(251,191,36,0.15)' }}>
            <span
              className="font-mono font-bold rounded-lg text-center shrink-0"
              style={{ fontSize: 10, width: 54, padding: '3px 0', background: buy ? 'rgba(16,217,160,0.14)' : 'rgba(255,176,32,0.14)', color: buy ? 'var(--gain)' : '#ffb020' }}
            >
              {buy ? 'BUY' : 'SELL'}
            </span>
            <button
              onClick={() => openPlayer?.(o.player_id)}
              disabled={!openPlayer}
              className="flex-1 min-w-0 text-left"
            >
              <p className="text-foreground font-semibold truncate" style={{ fontSize: 14 }}>
                {m ? (m.real_name || m.gamertag) : 'Player'}
              </p>
              <p className="text-muted-foreground truncate" style={{ fontSize: 11.5 }}>
                {left.toLocaleString()} of {o.quantity.toLocaleString()} shares left at {usd(toNumber(o.limit_price ?? 0))}
                {o.status === 'partially_filled' ? ' · partly filled' : ''}
                {' · '}
                <span style={{ color: o.expires_at ? AMBER : undefined }}>{expiryText(o.expires_at)}</span>
              </p>
            </button>
            <span className="font-mono font-bold text-foreground shrink-0 text-right" style={{ fontSize: 13.5, minWidth: 96 }} title={buy ? 'Cash this buy order will spend if it fills in full (before fees)' : 'What this sell order will bring in if it fills in full (before fees)'}>
              {usd(worth(o))}
            </span>
            {editing === o.id ? (
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-muted-foreground font-mono" style={{ fontSize: 13 }}>$</span>
                <input
                  autoFocus
                  type="number"
                  step="0.01"
                  min="0"
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') savePrice(o); if (e.key === 'Escape') setEditing(null); }}
                  className="rounded-lg font-mono text-foreground"
                  style={{ width: 92, fontSize: 13, padding: '6px 8px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(251,191,36,0.6)' }}
                  aria-label="New price per share"
                />
                <button
                  onClick={() => savePrice(o)}
                  disabled={busy !== null}
                  className="px-3 py-2 rounded-lg font-bold transition-opacity hover:opacity-90 disabled:opacity-50"
                  style={{ fontSize: 12.5, background: AMBER, color: '#111' }}
                >
                  {busy === o.id ? 'Saving…' : 'Save'}
                </button>
                <button onClick={() => setEditing(null)} disabled={busy !== null} className="px-2 py-2 text-muted-foreground" style={{ fontSize: 12.5 }}>
                  Close
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  onClick={() => { setEditing(o.id); setDraft(String(toNumber(o.limit_price ?? 0))); setError(null); }}
                  disabled={busy !== null}
                  className="px-3 py-2 rounded-lg font-bold transition-opacity hover:opacity-90 disabled:opacity-50"
                  style={{ fontSize: 12.5, background: 'rgba(251,191,36,0.14)', border: '1px solid rgba(251,191,36,0.6)', color: AMBER }}
                  title="Change this order's price without cancelling it"
                >
                  Edit price
                </button>
                <button
                  onClick={() => cancel(o.id)}
                  disabled={busy !== null}
                  className="px-4 py-2 rounded-lg font-bold transition-opacity hover:opacity-90 disabled:opacity-50"
                  style={{ fontSize: 12.5, background: 'rgba(255,61,92,0.15)', border: '1px solid var(--loss)', color: 'var(--loss)' }}
                >
                  {busy === o.id ? 'Cancelling…' : 'Cancel order'}
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** A bright strip for Home / anywhere: shows only when the user has open orders and sends them to My Portfolio to cancel. */
export function OpenOrdersBanner({ onReview }: { onReview: () => void }) {
  const { orders } = useOpenOrders();
  if (!orders || orders.length === 0) return null;
  return (
    <button
      onClick={onReview}
      className="w-full flex items-center gap-3 px-4 py-3 rounded-2xl text-left transition-opacity hover:opacity-90"
      style={{ background: 'rgba(251,191,36,0.10)', border: '1.5px solid rgba(251,191,36,0.55)' }}
    >
      <AlertTriangle className="w-5 h-5 shrink-0" style={{ color: AMBER }} />
      <span className="flex-1" style={{ fontSize: 13.5, color: 'var(--foreground)' }}>
        <strong>{orders.length} open order{orders.length > 1 ? 's' : ''}</strong> still waiting on the market.
      </span>
      <span className="font-bold shrink-0" style={{ fontSize: 13, color: AMBER }}>Review &amp; cancel</span>
    </button>
  );
}

/** Count of open orders, for the sidebar badge. */
export function useOpenOrderCount(): number {
  const { orders } = useOpenOrders();
  return orders?.length ?? 0;
}
