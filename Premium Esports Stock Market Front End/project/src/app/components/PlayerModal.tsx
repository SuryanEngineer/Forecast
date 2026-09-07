import { useEffect, useRef, useState } from 'react';
import { X, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { motion } from 'motion/react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { api, ApiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { toNumber, type MarketSnapshot, type PositionResponse, type PriceHistoryPoint, type TradeResponse } from '../lib/types';
import { colorForId } from '../lib/colors';
import { PlayerAvatar } from './Dashboard';
import { HelpButton } from './HelpModal';

interface Props {
  playerId: string;
  onClose: () => void;
}

const ChartTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2 border border-border" style={{ background: 'var(--popover)' }}>
      <p className="font-mono font-bold text-foreground" style={{ fontSize: 14 }}>${payload[0].value.toFixed(2)}</p>
    </div>
  );
};

function playerName(m: MarketSnapshot): string {
  return m.real_name || m.gamertag;
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

/** A recent-trades tape for this one player -- the closest real-data
 * equivalent to ForecastDemo's live bid/ask order-book ladder that the
 * real backend can currently support. NOTE: the real forecast-backend
 * has no order-book depth endpoint (no GET .../orderbook or
 * .../quick-quote, unlike the demo's in-memory equivalents -- see
 * forecast-backend/app/api/v1/markets.py and orders.py), so this shows
 * actual recent fills (GET /orders/trades/{player_id}) instead of a
 * fabricated bids/asks ladder. Reaching full parity with the demo's
 * order-book UI would need new backend endpoints; see this task's final
 * report. */
function RecentTrades({ trades }: { trades: TradeResponse[] }) {
  if (trades.length === 0) {
    return (
      <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
        <p className="text-muted-foreground" style={{ fontSize: 12 }}>No trades yet -- be the first to trade this player!</p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-border overflow-hidden" style={{ background: 'var(--muted)' }}>
      <div className="px-3 pt-2 pb-1">
        <p className="text-muted-foreground font-semibold" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.03em' }}>Recent trades</p>
      </div>
      <div className="px-1.5 pb-1.5 space-y-0.5">
        {trades.slice(0, 8).map(t => (
          <div key={t.id} className="w-full flex items-center justify-between px-2 py-1 rounded-lg" style={{ fontSize: 12 }}>
            <span className="font-mono font-bold text-foreground">${toNumber(t.price).toFixed(2)}</span>
            <span className="font-mono text-muted-foreground">{t.quantity} sh</span>
            <span className="text-muted-foreground" style={{ fontSize: 10.5 }}>{timeAgo(t.executed_at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PlayerModal({ playerId, onClose }: Props) {
  const { refreshWallet } = useAuth();
  const [market, setMarket] = useState<MarketSnapshot | null>(null);
  const [position, setPosition] = useState<PositionResponse | null>(null);
  const [history, setHistory] = useState<PriceHistoryPoint[]>([]);
  const [recentTrades, setRecentTrades] = useState<TradeResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const [tradeMode, setTradeMode] = useState<'quick' | 'order'>('quick');
  const [orderSide, setOrderSide] = useState<'buy' | 'sell'>('buy');
  const [limitPrice, setLimitPrice] = useState('');
  const [orderShares, setOrderShares] = useState('1');
  const [quickQty, setQuickQty] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [m, h, trades] = await Promise.all([
        api.get<MarketSnapshot>(`/markets/${playerId}`),
        api.get<PriceHistoryPoint[]>(`/markets/${playerId}/price-history?limit=60`),
        api.get<TradeResponse[]>(`/orders/trades/${playerId}?limit=8`).catch(() => []),
      ]);
      setMarket(m);
      setHistory(h);
      setRecentTrades(trades);
      try {
        const p = await api.get<PositionResponse>(`/players/${playerId}/position`);
        setPosition(p);
      } catch {
        setPosition(null);
      }
    } catch (e) {
      setMessage({ kind: 'error', text: e instanceof ApiError ? e.message : 'Failed to load player' });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId]);

  // Keep the recent-trades tape fresh while the modal is open -- other
  // traders (and bots) keep trading in the background. Routed through a
  // ref so the interval doesn't need to be torn down/recreated.
  const refreshTradesRef = useRef<() => void>(() => {});
  refreshTradesRef.current = () => {
    api.get<TradeResponse[]>(`/orders/trades/${playerId}?limit=8`).then(setRecentTrades).catch(() => {});
  };
  useEffect(() => {
    const id = setInterval(() => refreshTradesRef.current(), 8000);
    return () => clearInterval(id);
  }, [playerId]);

  if (loading && !market) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.65)' }}>
        <p className="text-muted-foreground" style={{ fontSize: 14 }}>Loading…</p>
      </div>
    );
  }
  if (!market) {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        style={{ background: 'rgba(0,0,0,0.65)' }}
        onClick={onClose}
      >
        <div className="rounded-2xl border border-border p-6" style={{ background: 'var(--card)' }}>
          <p style={{ color: 'var(--loss)' }}>{message?.text || 'Player not found'}</p>
        </div>
      </div>
    );
  }

  const price = toNumber(market.last_price);
  const changePct = toNumber(market.change_pct);
  const isUp = changePct >= 0;
  const chartColor = isUp ? '#10d9a0' : '#ff3d5c';
  const color = colorForId(market.id);

  const chartData = history.map(h => ({
    date: new Date(h.recorded_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    price: toNumber(h.price),
  }));

  async function handleQuick(side: 'buy' | 'sell') {
    setSubmitting(true);
    setMessage(null);
    try {
      await api.post('/orders/quick', { player_id: playerId, side, quantity: quickQty });
      setMessage({ kind: 'success', text: `Quick ${side} of ${quickQty} share${quickQty !== 1 ? 's' : ''} filled!` });
      await Promise.all([load(), refreshWallet()]);
    } catch (e) {
      setMessage({ kind: 'error', text: e instanceof ApiError ? e.message : 'Order failed' });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLimitOrder() {
    const priceVal = parseFloat(limitPrice);
    const shares = parseInt(orderShares, 10);
    if (!priceVal || !shares || priceVal <= 0 || shares <= 0) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await api.post('/orders/limit', { player_id: playerId, side: orderSide, price: priceVal, quantity: shares });
      setMessage({ kind: 'success', text: `Limit ${orderSide} order placed for ${shares} share${shares !== 1 ? 's' : ''} at $${priceVal.toFixed(2)}.` });
      setLimitPrice('');
      setOrderShares('1');
      await Promise.all([load(), refreshWallet()]);
    } catch (e) {
      setMessage({ kind: 'error', text: e instanceof ApiError ? e.message : 'Order failed' });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border"
        style={{ background: 'var(--card)', maxWidth: 780, maxHeight: '90vh', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="px-6 pt-5 pb-4 flex items-start gap-4" style={{ background: `linear-gradient(135deg, ${color}14, transparent 60%)` }}>
          <PlayerAvatar name={playerName(market)} color={color} size={60} />
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-foreground font-bold" style={{ fontSize: 24 }}>{playerName(market)}</h2>
                <div className="flex items-center gap-2 mt-0.5">
                  {market.team && (
                    <span className="px-2 py-0.5 rounded-lg text-sm font-medium" style={{ background: color + '22', color }}>{market.team}</span>
                  )}
                  {market.region && <span className="text-muted-foreground" style={{ fontSize: 13 }}>{market.region}</span>}
                </div>
              </div>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0">
                <X className="w-5 h-5 text-muted-foreground" />
              </button>
            </div>
            <div className="flex items-center gap-3 mt-2">
              <span className="font-mono font-bold" style={{ fontSize: 28, color: 'var(--foreground)', letterSpacing: '-0.5px' }}>
                ${price.toFixed(2)}
              </span>
              <span
                className="inline-flex items-center gap-1 font-mono font-bold px-2.5 py-0.5 rounded-full"
                style={{ fontSize: 13, background: isUp ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)', color: isUp ? 'var(--gain)' : 'var(--loss)' }}
              >
                {isUp ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                {isUp ? '+' : ''}{changePct.toFixed(2)}% (24h)
              </span>
            </div>
            {position && position.quantity > 0 && (
              <p className="text-muted-foreground mt-2" style={{ fontSize: 12 }}>
                You own {position.quantity} share{position.quantity !== 1 ? 's' : ''} (avg cost ${toNumber(position.average_cost).toFixed(2)})
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-0 md:grid-cols-[1fr_280px]">
          <div className="px-6 pb-6 border-r border-border space-y-5">
            <div>
              <p className="text-muted-foreground mb-2" style={{ fontSize: 12 }}>Recent price</p>
              {chartData.length > 1 ? (
                <ResponsiveContainer width="100%" height={130}>
                  <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id={`mg-${market.id}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={chartColor} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={chartColor} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fill: '#5a6a82', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                    <YAxis tick={{ fill: '#5a6a82', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v.toFixed(0)}`} width={44} domain={['auto', 'auto']} />
                    <Tooltip content={<ChartTooltip />} />
                    <Area type="monotone" dataKey="price" stroke={chartColor} fill={`url(#mg-${market.id})`} strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-muted-foreground" style={{ fontSize: 13 }}>No trade history yet -- be the first to trade this player!</p>
              )}
            </div>

            <div className="grid grid-cols-4 gap-2">
              {[
                { label: '24h Volume', value: market.volume_24h.toLocaleString(), emoji: '📊' },
                { label: 'Market Cap', value: `$${(toNumber(market.market_cap) / 1000).toFixed(0)}k`, emoji: '💵' },
                { label: 'Shares Out', value: market.total_shares_outstanding.toLocaleString(), emoji: '🧾' },
                { label: 'IPO Price', value: `$${toNumber(market.ipo_price).toFixed(2)}`, emoji: '🚀' },
              ].map(s => (
                <div key={s.label} className="rounded-xl border border-border p-2.5 text-center" style={{ background: 'var(--muted)' }}>
                  <p style={{ fontSize: 16 }}>{s.emoji}</p>
                  <p className="font-mono font-bold" style={{ fontSize: 14, color: 'var(--foreground)', marginTop: 2 }}>{s.value}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 10 }}>{s.label}</p>
                </div>
              ))}
            </div>

            {message && (
              <div
                className="rounded-xl p-3"
                style={{
                  background: message.kind === 'success' ? 'rgba(16,217,160,0.1)' : 'rgba(255,61,92,0.1)',
                  color: message.kind === 'success' ? 'var(--gain)' : 'var(--loss)',
                  fontSize: 13,
                }}
              >
                {message.text}
              </div>
            )}
          </div>

          <div className="px-5 pt-5 pb-6 space-y-4">
            <div className="flex items-center gap-1.5">
              <p className="text-foreground font-bold" style={{ fontSize: 17 }}>Trade</p>
              <HelpButton topic="orders" />
            </div>

            <RecentTrades trades={recentTrades} />

            <div className="flex rounded-xl overflow-hidden border border-border">
              <button
                onClick={() => setTradeMode('quick')}
                className="flex-1 py-2 font-semibold transition-all"
                style={{ fontSize: 13, background: tradeMode === 'quick' ? 'rgba(0,200,255,0.1)' : 'transparent', color: tradeMode === 'quick' ? 'var(--primary)' : 'var(--muted-foreground)' }}
              >
                ⚡ Quick
              </button>
              <button
                onClick={() => setTradeMode('order')}
                className="flex-1 py-2 font-semibold transition-all"
                style={{ fontSize: 13, background: tradeMode === 'order' ? 'rgba(155,111,255,0.1)' : 'transparent', color: tradeMode === 'order' ? 'var(--accent)' : 'var(--muted-foreground)' }}
              >
                🎯 Limit Order
              </button>
            </div>

            {tradeMode === 'quick' ? (
              <div className="space-y-3">
                <p className="text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.5 }}>
                  Buy or sell right now at the current market price. No waiting.
                </p>
                <div>
                  <p className="text-muted-foreground mb-2" style={{ fontSize: 12 }}>Shares</p>
                  <div className="grid grid-cols-4 gap-1.5 mb-2">
                    {[1, 5, 10, 25].map(n => (
                      <button
                        key={n}
                        onClick={() => setQuickQty(n)}
                        className="py-2 rounded-xl font-mono font-bold transition-all"
                        style={{
                          fontSize: 15,
                          background: quickQty === n ? 'rgba(0,200,255,0.12)' : 'var(--muted)',
                          color: quickQty === n ? 'var(--primary)' : 'var(--foreground)',
                          border: quickQty === n ? '1.5px solid rgba(0,200,255,0.35)' : '1.5px solid var(--border)',
                        }}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                  <input
                    type="number"
                    min={1}
                    value={quickQty}
                    onChange={e => setQuickQty(Math.max(1, parseInt(e.target.value, 10) || 1))}
                    className="w-full px-3 py-2.5 rounded-xl border border-border font-mono text-foreground text-center outline-none"
                    style={{ background: 'var(--muted)', fontSize: 16, fontWeight: 700 }}
                  />
                </div>
                <div className="rounded-xl p-3 border border-border text-center" style={{ background: 'var(--muted)' }}>
                  <p className="text-muted-foreground" style={{ fontSize: 12 }}>Estimated cost</p>
                  <p className="font-mono font-bold text-foreground" style={{ fontSize: 20 }}>${(quickQty * price).toFixed(2)}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 10 }}>plus a small transaction fee</p>
                </div>
                <button
                  disabled={submitting}
                  onClick={() => handleQuick('buy')}
                  className="w-full py-3 rounded-xl font-bold transition-all"
                  style={{ fontSize: 15, background: submitting ? 'rgba(255,255,255,0.08)' : 'linear-gradient(135deg, #10d9a0, #00c8ff)', color: '#fff' }}
                >
                  {submitting ? 'Placing…' : `⚡ Quick Buy ${quickQty} Share${quickQty !== 1 ? 's' : ''}`}
                </button>
                <button
                  disabled={submitting || !position || position.available_quantity < quickQty}
                  onClick={() => handleQuick('sell')}
                  className="w-full py-3 rounded-xl font-bold transition-all"
                  style={{
                    fontSize: 15,
                    background: 'rgba(255,61,92,0.12)',
                    color: 'var(--loss)',
                    border: '1.5px solid rgba(255,61,92,0.3)',
                    opacity: !position || position.available_quantity < quickQty ? 0.5 : 1,
                  }}
                >
                  ⚡ Quick Sell {quickQty} Share{quickQty !== 1 ? 's' : ''}
                </button>
                <p className="text-muted-foreground text-center" style={{ fontSize: 11 }}>
                  ⚡ Quick trades execute instantly at market price
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.5 }}>
                  Set a limit price. Your order rests on the order book until it fills (or you cancel it).
                </p>
                <div className="flex rounded-xl overflow-hidden border border-border">
                  {(['buy', 'sell'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => setOrderSide(t)}
                      className="flex-1 py-2.5 font-bold capitalize transition-all"
                      style={{
                        fontSize: 14,
                        background: orderSide === t ? (t === 'buy' ? 'rgba(16,217,160,0.15)' : 'rgba(255,61,92,0.15)') : 'transparent',
                        color: orderSide === t ? (t === 'buy' ? 'var(--gain)' : 'var(--loss)') : 'var(--muted-foreground)',
                      }}
                    >
                      {t === 'buy' ? '↑ Buy Order' : '↓ Sell Order'}
                    </button>
                  ))}
                </div>

                <div>
                  <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Limit price</label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground font-mono" style={{ fontSize: 15 }}>$</span>
                    <input
                      type="number"
                      min={0.01}
                      step={0.01}
                      placeholder={price.toFixed(2)}
                      value={limitPrice}
                      onChange={e => setLimitPrice(e.target.value)}
                      className="w-full pl-7 pr-3 py-2.5 rounded-xl border border-border font-mono text-foreground outline-none transition-colors focus:border-primary/50"
                      style={{ background: 'var(--muted)', fontSize: 16 }}
                    />
                  </div>
                  <p className="text-muted-foreground mt-1" style={{ fontSize: 11 }}>Current price: ${price.toFixed(2)}</p>
                </div>

                <div>
                  <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Number of shares</label>
                  <input
                    type="number"
                    min={1}
                    placeholder="1"
                    value={orderShares}
                    onChange={e => setOrderShares(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl border border-border font-mono text-foreground text-center outline-none"
                    style={{ background: 'var(--muted)', fontSize: 16 }}
                  />
                </div>

                <button
                  onClick={handleLimitOrder}
                  disabled={!limitPrice || !orderShares || submitting}
                  className="w-full py-3 rounded-xl font-bold transition-all"
                  style={{
                    fontSize: 15,
                    background: (!limitPrice || !orderShares || submitting) ? 'rgba(255,255,255,0.05)' : 'linear-gradient(135deg, var(--accent), #6366f1)',
                    color: (!limitPrice || !orderShares || submitting) ? 'var(--muted-foreground)' : '#fff',
                    cursor: (!limitPrice || !orderShares || submitting) ? 'not-allowed' : 'pointer',
                  }}
                >
                  {submitting ? 'Placing…' : `🎯 Place ${orderSide === 'buy' ? 'Buy' : 'Sell'} Order`}
                </button>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
