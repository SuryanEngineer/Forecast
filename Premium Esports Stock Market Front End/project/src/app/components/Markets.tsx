import { useState, useEffect, useRef } from 'react';
import { Search, TrendingUp, TrendingDown, X, MessageCircle } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { api } from '../lib/api';
import { useLeaderboard, useMarkets } from '../lib/hooks';
import { toNumber, type MarketSnapshot, type TradeResponse } from '../lib/types';
import { colorForId } from '../lib/colors';
import { PlayerAvatar } from './Dashboard';
import { HelpButton } from './HelpModal';
import { InfoDot } from './InfoTooltip';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  initialSearch?: string;
  onSearchChange?: (term: string) => void;
}

function formatCompactCurrency(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

interface FeedTrade extends TradeResponse {
  gamertag: string;
}

// How many of the currently-hottest (by 24h volume) players to poll
// individual recent-trade history for, to build the "Live Activity"
// feed below. The real backend has no single "recent trades across
// every player" endpoint (see forecast-backend/app/api/v1/orders.py --
// GET /orders/trades/{player_id} is per-player only), so this polls a
// bounded, capped set of the most active players instead of all of
// them (which could be 100+ parallel requests every poll on a big
// roster). This means the feed is a real (if partial) window into
// market activity, not a fabricated one -- it just doesn't guarantee
// catching every single trade on a quiet player.
const LIVE_FEED_PLAYER_CAP = 12;
const LIVE_FEED_POLL_MS = 10_000;

function useLiveTradeFeed(markets: MarketSnapshot[]) {
  const [trades, setTrades] = useState<FeedTrade[]>([]);
  const marketsRef = useRef(markets);
  marketsRef.current = markets;

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const active = [...marketsRef.current].sort((a, b) => b.volume_24h - a.volume_24h).slice(0, LIVE_FEED_PLAYER_CAP);
      if (active.length === 0) return;
      const results = await Promise.allSettled(
        active.map(m => api.get<TradeResponse[]>(`/orders/trades/${m.id}?limit=8`))
      );
      if (cancelled) return;
      const byId = new Map(active.map(m => [m.id, m]));
      const merged: FeedTrade[] = [];
      results.forEach((res, i) => {
        if (res.status !== 'fulfilled') return;
        const market = byId.get(active[i].id);
        if (!market) return;
        for (const t of res.value) {
          merged.push({ ...t, gamertag: market.real_name || market.gamertag });
        }
      });
      merged.sort((a, b) => new Date(b.executed_at).getTime() - new Date(a.executed_at).getTime());
      setTrades(merged.slice(0, 50));
    }

    poll();
    const id = setInterval(poll, LIVE_FEED_POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
    // Re-polls whenever the market roster's identity changes (new IPO) --
    // the interval itself doesn't need markets in its own closure since
    // it always reads the latest value via marketsRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markets.length]);

  return trades;
}

const SORTS = [
  { key: 'hot', label: '🔥 Hottest' },
  { key: 'price', label: '💰 Price' },
  { key: 'volume', label: '📊 Most Traded' },
] as const;
type SortKey = typeof SORTS[number]['key'];

function displayName(m: MarketSnapshot): string {
  return m.real_name || m.gamertag;
}

function PlayerCard({ market, navigate }: { market: MarketSnapshot; navigate: Props['navigate'] }) {
  const price = toNumber(market.last_price);
  const changePct = toNumber(market.change_pct);
  const isUp = changePct >= 0;
  const color = colorForId(market.id);

  return (
    <div
      className="rounded-2xl border border-border overflow-hidden flex flex-col cursor-pointer"
      style={{ background: 'var(--card)', transition: 'transform 0.15s ease, box-shadow 0.15s ease' }}
      onClick={() => navigate('player', market.id)}
    >
      <div className="px-4 pt-4 pb-3" style={{ background: `linear-gradient(135deg, ${color}18, transparent 70%)` }}>
        <div className="flex items-start justify-between">
          <PlayerAvatar name={displayName(market)} color={color} size={50} />
          <span
            className="flex items-center gap-0.5 px-2.5 py-1 rounded-full font-mono font-bold"
            style={{
              fontSize: 13,
              background: isUp ? 'rgba(16,217,160,0.15)' : 'rgba(255,61,92,0.15)',
              color: isUp ? 'var(--gain)' : 'var(--loss)',
            }}
          >
            {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="px-4 pb-4 flex flex-col flex-1">
        <p className="text-foreground font-bold" style={{ fontSize: 18 }}>{displayName(market)}</p>
        <div className="flex items-center gap-2 mt-0.5 mb-3">
          {market.team && (
            <span className="px-2 py-0.5 rounded-lg text-xs font-medium" style={{ background: color + '22', color }}>
              {market.team}
            </span>
          )}
          {market.region && <span className="text-muted-foreground" style={{ fontSize: 12 }}>{market.region}</span>}
        </div>

        <p className="font-mono font-bold mb-2" style={{ fontSize: 26, color: 'var(--foreground)', letterSpacing: '-0.5px' }}>
          ${price.toFixed(2)}
        </p>

        <div className="flex gap-4 mt-1 mb-4">
          <div>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>24H VOLUME</p>
            <p className="font-mono font-bold text-foreground" style={{ fontSize: 14 }}>{market.volume_24h.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>SHARES OUT</p>
            <p className="font-mono font-bold text-foreground" style={{ fontSize: 14 }}>{market.total_shares_outstanding.toLocaleString()}</p>
          </div>
        </div>

        <button
          onClick={e => { e.stopPropagation(); navigate('player', market.id); }}
          className="w-full py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90 mt-auto"
          style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
        >
          View &amp; Trade
        </button>
      </div>
    </div>
  );
}

/** Live trade "tape" -- recent buys/sells across the market's most
 * active players, as they happen. Unlike ForecastDemo's equivalent, this
 * can't label each print "Buy" or "Sell": the real backend's Trade rows
 * (see forecast-backend/app/models/order.py) record both sides of the
 * match (buyer_user_id/seller_user_id) but not which side was the taker
 * / aggressor, so there's no honest way to derive a buy/sell direction
 * here without guessing. Shown as a neutral trade print instead --
 * price, size, and player -- rather than fabricating a side. */
function LiveTradeFeed({ trades, navigate }: { trades: FeedTrade[]; navigate: Props['navigate'] }) {
  if (trades.length === 0) {
    return <p className="text-muted-foreground text-center py-6" style={{ fontSize: 13 }}>No trades yet -- activity will show up here as it happens.</p>;
  }
  return (
    <div className="space-y-1 overflow-y-auto pr-1 flex-1">
      {trades.map(t => {
        const color = colorForId(t.player_id);
        return (
          <button
            key={t.id}
            onClick={() => navigate('player', t.player_id)}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-left transition-colors hover:bg-white/[0.04]"
          >
            <span
              className="shrink-0 px-1.5 py-0.5 rounded font-mono font-bold uppercase"
              style={{ fontSize: 9.5, letterSpacing: '0.03em', background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}
            >
              Trade
            </span>
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
            <span className="text-foreground font-medium truncate" style={{ fontSize: 12.5 }}>{t.gamertag}</span>
            <span className="text-muted-foreground shrink-0" style={{ fontSize: 11.5 }}>{t.quantity} sh</span>
            <span className="flex-1" />
            <span className="font-mono font-bold text-foreground shrink-0" style={{ fontSize: 12.5 }}>${toNumber(t.price).toFixed(2)}</span>
            <span className="text-muted-foreground shrink-0" style={{ fontSize: 10.5, minWidth: 42, textAlign: 'right' }}>{timeAgo(t.executed_at)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Docked sidebar for watching live trades -- a real flex sibling of the
 * page content, not a `position: fixed` overlay, so opening it actually
 * shrinks the content column to make room. Independently toggleable from
 * Market Overview below (separate piece of UI, separate state). */
function LiveActivityPanel({ trades, navigate, onClose }: { trades: FeedTrade[]; navigate: Props['navigate']; onClose: () => void }) {
  return (
    <motion.div
      className="sticky top-0 self-start shrink-0 h-screen overflow-hidden border-l border-border"
      style={{ background: 'var(--card)' }}
      initial={{ width: 0 }}
      animate={{ width: 340 }}
      exit={{ width: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <div className="h-full flex flex-col" style={{ width: 340 }}>
        <div className="px-4 py-4 border-b border-border flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <MessageCircle className="w-4 h-4" style={{ color: 'var(--primary)' }} />
            <div>
              <p className="text-foreground font-bold" style={{ fontSize: 14 }}>Live Activity</p>
              <p className="text-muted-foreground" style={{ fontSize: 10.5 }}>Recent trades on the busiest players</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 transition-colors shrink-0">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>
        <div className="flex-1 overflow-hidden flex flex-col px-2 py-2">
          <LiveTradeFeed trades={trades} navigate={navigate} />
        </div>
      </div>
    </motion.div>
  );
}

export function Markets({ navigate, initialSearch = '', onSearchChange }: Props) {
  const { data: markets, loading, error } = useMarkets();
  const { data: leaderboard } = useLeaderboard();
  const liveTrades = useLiveTradeFeed(markets);
  const [search, setSearch] = useState(initialSearch);
  const [sort, setSort] = useState<SortKey>('hot');
  // Collapsed by default -- Market Overview's stat grid is useful detail,
  // not something that should eat up the top of the page before anyone's
  // asked to see it.
  const [showOverview, setShowOverview] = useState(false);
  // Deliberately a separate boolean from showOverview -- opening Market
  // Overview shouldn't force Live Activity open too (a stat snapshot and
  // a running trade ticker are unrelated views someone might want open
  // independently of each other).
  const [showLiveActivity, setShowLiveActivity] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSearch(initialSearch);
    if (initialSearch) searchRef.current?.focus();
  }, [initialSearch]);

  function handleSearch(val: string) {
    setSearch(val);
    onSearchChange?.(val);
  }

  const sorted = [...markets].sort((a, b) => {
    if (sort === 'hot') return Math.abs(toNumber(b.change_pct)) - Math.abs(toNumber(a.change_pct));
    if (sort === 'price') return toNumber(b.last_price) - toNumber(a.last_price);
    if (sort === 'volume') return b.volume_24h - a.volume_24h;
    return 0;
  });

  const filtered = sorted.filter(m => {
    if (!search) return true;
    const term = search.toLowerCase();
    return displayName(m).toLowerCase().includes(term) || (m.team ?? '').toLowerCase().includes(term);
  });

  const totalMarketCap = markets.reduce((s, m) => s + toNumber(m.market_cap), 0);
  const totalVolume = markets.reduce((s, m) => s + m.volume_24h, 0);
  // Count players with actual trading volume, not just the whole listed
  // roster -- so this reads as an activity signal, not "how many players
  // have ever been IPO'd."
  const playersTradingCount = markets.filter(m => m.volume_24h > 0).length;
  const byChange = [...markets].sort((a, b) => toNumber(b.change_pct) - toNumber(a.change_pct));
  const topGainers = byChange.slice(0, 5).filter(m => toNumber(m.change_pct) > 0);
  const topLosers = byChange.slice(-5).reverse().filter(m => toNumber(m.change_pct) < 0);
  // Sum of every ranked investor's cash_balance -- GET /leaderboard
  // already excludes bots and the House account (see
  // leaderboard_service.py), so this is a real, honest read of "cash
  // real traders are holding." Note this reflects only the leaderboard's
  // default page (100 investors, per useLeaderboard()'s '/leaderboard'
  // call with no limit override) -- exact at prototype scale, but would
  // need a higher `?limit=` once the user count exceeds that. Not a
  // fabricated estimate either way -- just an aggregation of
  // already-fetched real data.
  const moneyInCirculation = leaderboard.reduce((s, e) => s + toNumber(e.cash_balance), 0);

  return (
    <div className="flex items-start">
      <div className="flex-1 min-w-0 p-6 max-w-[1100px] mx-auto space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5">
            <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Player Market</h1>
            <HelpButton topic="market" size={17} />
          </div>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Buy shares of your favorite Fortnite pros. When they do well, you earn money!
        </p>
        </div>
        <button
          onClick={() => setShowLiveActivity(v => !v)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl font-semibold shrink-0 transition-colors"
          style={{
            fontSize: 12.5,
            background: showLiveActivity ? 'rgba(0,200,255,0.14)' : 'var(--card)',
            color: showLiveActivity ? 'var(--primary)' : 'var(--muted-foreground)',
            border: showLiveActivity ? '1.5px solid rgba(0,200,255,0.35)' : '1.5px solid var(--border)',
          }}
        >
          <MessageCircle className="w-3.5 h-3.5" />
          {showLiveActivity ? 'Hide Live Activity' : 'Live Activity'}
        </button>
      </div>

      {error && (
        <div className="rounded-2xl border p-4" style={{ borderColor: 'rgba(255,61,92,0.3)', background: 'rgba(255,61,92,0.06)' }}>
          <p style={{ fontSize: 13, color: 'var(--loss)' }}>Couldn't reach the Forecast API ({error}). Is the backend running?</p>
        </div>
      )}

      <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
        <button
          onClick={() => setShowOverview(v => !v)}
          className="w-full flex items-center justify-between px-5 py-4 text-left"
        >
          <div>
            <p className="text-foreground font-semibold" style={{ fontSize: 16 }}>📈 Market Overview</p>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>Tap to see market-wide stats</p>
          </div>
          <span className="text-muted-foreground" style={{ fontSize: 12 }}>{showOverview ? 'Hide ▲' : 'Show ▼'}</span>
        </button>

        {showOverview && (
          <div className="px-5 pb-5 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <div className="flex items-center justify-center gap-1">
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>Total Market Cap</p>
                  <InfoDot text="The combined value of every pro player's shares outstanding, at their current price. Goes up when player prices rise or a new player IPOs -- doesn't include anyone's cash." />
                </div>
                <p className="font-mono font-bold text-foreground mt-0.5" style={{ fontSize: 18 }}>{formatCompactCurrency(totalMarketCap)}</p>
              </div>
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <div className="flex items-center justify-center gap-1">
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>Money in Circulation</p>
                  <InfoDot text="Total cash held by every ranked investor right now (from the Rankings leaderboard) -- not the exchange's own reserve. Grows when new users register or dividends get paid out." align="right" />
                </div>
                <p className="font-mono font-bold text-foreground mt-0.5" style={{ fontSize: 18 }}>{formatCompactCurrency(moneyInCirculation)}</p>
              </div>
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <div className="flex items-center justify-center gap-1">
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>24h Volume (shares)</p>
                  <InfoDot text="How many total shares have changed hands across every player in the last 24 hours. Higher means the market's more active right now." />
                </div>
                <p className="font-mono font-bold text-foreground mt-0.5" style={{ fontSize: 18 }}>{totalVolume.toLocaleString()}</p>
              </div>
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <div className="flex items-center justify-center gap-1">
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>Players Trading</p>
                  <InfoDot text="How many listed players have actually had a share change hands recently -- not just the total roster size." align="right" />
                </div>
                <p className="font-mono font-bold text-foreground mt-0.5" style={{ fontSize: 18 }}>{playersTradingCount}</p>
                <p className="text-muted-foreground mt-0.5" style={{ fontSize: 9.5 }}>of {markets.length} listed</p>
              </div>
            </div>

            {!showLiveActivity && (
              <button
                onClick={() => setShowLiveActivity(true)}
                className="w-full flex items-center gap-2 py-2 px-3 rounded-xl transition-colors hover:opacity-90"
                style={{ fontSize: 12, background: 'rgba(0,200,255,0.06)', color: 'var(--primary)' }}
              >
                <MessageCircle className="w-3.5 h-3.5 shrink-0" />
                Want to watch trades happen live? Open Live Activity →
              </button>
            )}

            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <p className="text-foreground font-semibold" style={{ fontSize: 13 }}>🎮 Top Player Stocks</p>
                <InfoDot text="These rankings are about pro player stock prices moving, not user portfolios or account balances." />
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-border p-3" style={{ background: 'var(--muted)' }}>
                  <p className="flex items-center gap-1.5 font-semibold mb-2" style={{ fontSize: 12, color: 'var(--gain)' }}>
                    <TrendingUp className="w-3.5 h-3.5" /> Gainers (players)
                  </p>
                  {topGainers.length === 0 ? (
                    <p className="text-muted-foreground" style={{ fontSize: 12 }}>Nothing's up right now.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {topGainers.map(m => (
                        <button key={m.id} onClick={() => navigate('player', m.id)} className="w-full flex items-center justify-between hover:opacity-80">
                          <span className="text-foreground" style={{ fontSize: 12.5 }}>{displayName(m)}</span>
                          <span className="font-mono font-bold" style={{ fontSize: 12.5, color: 'var(--gain)' }}>+{toNumber(m.change_pct).toFixed(2)}%</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="rounded-xl border border-border p-3" style={{ background: 'var(--muted)' }}>
                  <p className="flex items-center gap-1.5 font-semibold mb-2" style={{ fontSize: 12, color: 'var(--loss)' }}>
                    <TrendingDown className="w-3.5 h-3.5" /> Losers (players)
                  </p>
                  {topLosers.length === 0 ? (
                    <p className="text-muted-foreground" style={{ fontSize: 12 }}>Nothing's down right now.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {topLosers.map(m => (
                        <button key={m.id} onClick={() => navigate('player', m.id)} className="w-full flex items-center justify-between hover:opacity-80">
                          <span className="text-foreground" style={{ fontSize: 12.5 }}>{displayName(m)}</span>
                          <span className="font-mono font-bold" style={{ fontSize: 12.5, color: 'var(--loss)' }}>{toNumber(m.change_pct).toFixed(2)}%</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <input
          ref={searchRef}
          type="text"
          placeholder="Search players or teams..."
          value={search}
          onChange={e => handleSearch(e.target.value)}
          className="w-full pl-12 pr-4 py-3 rounded-2xl border border-border text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
          style={{ background: 'var(--card)', fontSize: 15 }}
          autoComplete="off"
        />
      </div>

      <div>
        <p className="text-muted-foreground mb-2" style={{ fontSize: 12 }}>Sort by</p>
        <div className="flex flex-wrap gap-2">
          {SORTS.map(s => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              className="px-4 py-1.5 rounded-xl font-medium transition-all"
              style={{
                fontSize: 13,
                background: sort === s.key ? 'rgba(155,111,255,0.12)' : 'var(--card)',
                color: sort === s.key ? 'var(--accent)' : 'var(--muted-foreground)',
                border: sort === s.key ? '1.5px solid rgba(155,111,255,0.35)' : '1.5px solid var(--border)',
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {loading && markets.length === 0 ? (
        <div className="py-20 text-center text-muted-foreground" style={{ fontSize: 14 }}>Loading players…</div>
      ) : filtered.length === 0 ? (
        <div className="py-20 text-center">
          <p style={{ fontSize: 40 }}>🔍</p>
          <p className="text-muted-foreground mt-3" style={{ fontSize: 16 }}>
            {markets.length === 0 ? 'No players have been IPO\'d yet -- ask an admin to create one.' : `No players match "${search}"`}
          </p>
        </div>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
          {filtered.map(m => (
            <PlayerCard key={m.id} market={m} navigate={navigate} />
          ))}
        </div>
      )}
      </div>

      <AnimatePresence>
        {showLiveActivity && (
          <LiveActivityPanel trades={liveTrades} navigate={navigate} onClose={() => setShowLiveActivity(false)} />
        )}
      </AnimatePresence>
    </div>
  );
}
