import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useMarkets, useMyPositions } from '../lib/hooks';
import { toNumber, type MarketSnapshot } from '../lib/types';
import { colorForId } from '../lib/colors';
import { PlayerAvatar } from './Dashboard';
import { HelpButton } from './HelpModal';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openPlayer: (id: string) => void;
}

function playerName(m: MarketSnapshot): string {
  return m.real_name || m.gamertag;
}

export function Portfolio({ navigate, openPlayer }: Props) {
  const { wallet } = useAuth();
  const { data: markets, loading: marketsLoading } = useMarkets();
  const { data: positions, loading: positionsLoading } = useMyPositions();
  const [activeHoldingId, setActiveHoldingId] = useState<string | null>(null);

  const marketById = new Map(markets.map(m => [m.id, m]));
  const cashBalance = wallet ? toNumber(wallet.cash_balance) : 0;

  const holdings = positions
    .map(p => {
      const market = marketById.get(p.player_id);
      if (!market) return null;
      const price = toNumber(market.last_price);
      const currentVal = p.quantity * price;
      const costVal = p.quantity * toNumber(p.average_cost);
      const pl = currentVal - costVal;
      const plPct = costVal > 0 ? (pl / costVal) * 100 : 0;
      return { playerId: p.player_id, shares: p.quantity, market, currentVal, costVal, pl, plPct, color: colorForId(p.player_id) };
    })
    .filter((h): h is NonNullable<typeof h> => h !== null)
    .sort((a, b) => b.currentVal - a.currentVal);

  const totalInvested = holdings.reduce((s, h) => s + h.currentVal, 0);
  const totalCost = holdings.reduce((s, h) => s + h.costVal, 0);
  const totalPL = totalInvested - totalCost;
  const totalPLPct = totalCost > 0 ? (totalPL / totalCost) * 100 : 0;
  const grandTotal = totalInvested + cashBalance;

  const activeHolding = activeHoldingId ? holdings.find(h => h.playerId === activeHoldingId) : null;
  const loading = marketsLoading || positionsLoading;

  return (
    <div className="p-6 max-w-[900px] mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-1.5">
          <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>My Team</h1>
          <HelpButton topic="portfolio" size={17} />
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>All your players and how they're performing</p>
      </div>

      <div
        className="rounded-2xl border border-border p-6"
        style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.07), rgba(155,111,255,0.05)), var(--card)' }}
      >
        <p className="text-muted-foreground" style={{ fontSize: 14 }}>Portfolio Value</p>
        <p className="font-mono font-bold" style={{ fontSize: 42, color: 'var(--foreground)', letterSpacing: '-1px' }}>
          ${grandTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          {totalCost > 0 && (
            <span
              className="flex items-center gap-1 px-3 py-1 rounded-full font-mono font-bold"
              style={{ fontSize: 14, background: totalPL >= 0 ? 'rgba(16,217,160,0.15)' : 'rgba(255,61,92,0.15)', color: totalPL >= 0 ? 'var(--gain)' : 'var(--loss)' }}
            >
              {totalPL >= 0 ? '↑' : '↓'} {totalPL >= 0 ? '+' : ''}${totalPL.toFixed(2)} all time ({totalPLPct >= 0 ? '+' : ''}{totalPLPct.toFixed(1)}%)
            </span>
          )}
          <span className="text-muted-foreground" style={{ fontSize: 13 }}>${cashBalance.toLocaleString('en-US', { maximumFractionDigits: 2 })} cash left</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl border border-border p-4 text-center" style={{ background: 'var(--card)' }}>
          <p className="text-muted-foreground" style={{ fontSize: 12 }}>Players Owned</p>
          <p className="font-mono font-bold text-foreground" style={{ fontSize: 24 }}>{holdings.length}</p>
        </div>
        <div className="rounded-2xl border border-border p-4 text-center" style={{ background: 'var(--card)' }}>
          <p className="text-muted-foreground" style={{ fontSize: 12 }}>Cash Available</p>
          <p className="font-mono font-bold text-foreground" style={{ fontSize: 24, color: 'var(--primary)' }}>${cashBalance.toLocaleString('en-US', { maximumFractionDigits: 0 })}</p>
        </div>
      </div>

      {loading && holdings.length === 0 ? (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading your team…</p>
      ) : holdings.length === 0 ? (
        <div className="rounded-2xl border border-border p-10 text-center" style={{ background: 'var(--card)' }}>
          <p style={{ fontSize: 32 }}>🎒</p>
          <p className="text-muted-foreground mt-2" style={{ fontSize: 14 }}>You don't own any players yet.</p>
          <button
            onClick={() => navigate('markets')}
            className="mt-4 px-5 py-2.5 rounded-xl font-bold"
            style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
          >
            Browse the Market
          </button>
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
            <p className="text-foreground font-semibold mb-1" style={{ fontSize: 16 }}>Team Breakdown</p>
            <p className="text-muted-foreground mb-4" style={{ fontSize: 12 }}>Tap a player to see details</p>

            <div className="flex rounded-xl overflow-hidden h-10 mb-4" style={{ gap: 2 }}>
              {holdings.map(h => {
                const allocationPct = totalInvested > 0 ? (h.currentVal / totalInvested) * 100 : 0;
                return (
                  <button
                    key={h.playerId}
                    title={playerName(h.market)}
                    onClick={() => setActiveHoldingId(activeHoldingId === h.playerId ? null : h.playerId)}
                    className="h-full flex items-center justify-center transition-all"
                    style={{
                      width: `${allocationPct}%`,
                      background: h.color,
                      opacity: activeHoldingId && activeHoldingId !== h.playerId ? 0.35 : 1,
                      borderRadius: 8,
                      minWidth: 12,
                      cursor: 'pointer',
                      fontSize: 0,
                    }}
                  >
                    {allocationPct > 10 && (
                      <span className="font-mono font-bold" style={{ fontSize: 11, color: '#fff', pointerEvents: 'none' }}>
                        {allocationPct.toFixed(0)}%
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {activeHolding && (
              <div className="rounded-2xl p-4 border" style={{ background: `${activeHolding.color}0a`, borderColor: `${activeHolding.color}30` }}>
                <div className="flex items-center gap-3 mb-3">
                  <PlayerAvatar name={playerName(activeHolding.market)} color={activeHolding.color} size={44} />
                  <div className="flex-1">
                    <p className="text-foreground font-bold" style={{ fontSize: 16 }}>{playerName(activeHolding.market)}</p>
                    <p className="text-muted-foreground" style={{ fontSize: 12 }}>{activeHolding.shares} shares{activeHolding.market.team ? ` · ${activeHolding.market.team}` : ''}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-bold text-foreground" style={{ fontSize: 18 }}>${activeHolding.currentVal.toFixed(0)}</p>
                    <p className="font-mono font-bold" style={{ fontSize: 13, color: activeHolding.pl >= 0 ? 'var(--gain)' : 'var(--loss)' }}>
                      {activeHolding.pl >= 0 ? '+' : ''}${activeHolding.pl.toFixed(0)} ({activeHolding.plPct >= 0 ? '+' : ''}{activeHolding.plPct.toFixed(1)}%)
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => openPlayer(activeHolding.playerId)}
                  className="w-full py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
                  style={{ fontSize: 13, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
                >
                  View &amp; Trade
                </button>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
            <div className="px-5 py-4 border-b border-border flex items-center justify-between">
              <p className="text-foreground font-semibold" style={{ fontSize: 16 }}>Your Players</p>
              <button
                onClick={() => navigate('markets')}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl font-medium"
                style={{ fontSize: 13, background: 'var(--primary)', color: 'var(--primary-foreground)' }}
              >
                + Buy More
              </button>
            </div>

            {holdings.map((h, i) => (
              <button
                key={h.playerId}
                onClick={() => openPlayer(h.playerId)}
                className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-white/[0.03] transition-colors"
                style={{ borderBottom: i < holdings.length - 1 ? '1px solid var(--border)' : 'none' }}
              >
                <div className="w-1 h-10 rounded-full shrink-0" style={{ background: h.color }} />
                <PlayerAvatar name={playerName(h.market)} color={h.color} size={44} />
                <div className="flex-1 min-w-0">
                  <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>{playerName(h.market)}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 12 }}>{h.shares} shares{h.market.team ? ` · ${h.market.team}` : ''}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono font-bold text-foreground" style={{ fontSize: 16 }}>${h.currentVal.toFixed(0)}</p>
                  <span
                    className="font-mono font-bold px-2 py-0.5 rounded-lg"
                    style={{ fontSize: 12, background: h.pl >= 0 ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)', color: h.pl >= 0 ? 'var(--gain)' : 'var(--loss)' }}
                  >
                    {h.pl >= 0 ? '+' : ''}${h.pl.toFixed(0)} ({h.plPct >= 0 ? '+' : ''}{h.plPct.toFixed(1)}%)
                  </span>
                </div>
                <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
              </button>
            ))}

            <div className="flex items-center gap-4 px-5 py-4" style={{ borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
              <div className="w-1 h-10 rounded-full shrink-0 bg-white/20" />
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 font-mono font-bold" style={{ fontSize: 14, background: 'rgba(255,255,255,0.08)', color: 'var(--muted-foreground)' }}>
                $
              </div>
              <div className="flex-1">
                <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>Cash</p>
                <p className="text-muted-foreground" style={{ fontSize: 12 }}>Available to invest</p>
              </div>
              <div className="text-right">
                <p className="font-mono font-bold text-foreground" style={{ fontSize: 16 }}>${cashBalance.toFixed(0)}</p>
                <button onClick={() => navigate('markets')} className="text-primary" style={{ fontSize: 12 }}>Invest it →</button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
