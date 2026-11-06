import { useState } from 'react';
import { useMarkets } from '../lib/hooks';
import { toNumber } from '../lib/types';
import { usd } from '../lib/format';
import { LegalModal, SUPPORT_EMAIL, type LegalDoc } from './LegalModal';
import { PlayerModal } from './PlayerModal';
import { AccountPrompt } from './AccountPrompt';
import { GuestContext } from '../lib/guest';

const STEPS = [
  { n: '1', title: 'Pick your players', text: 'Every Fortnite pro has a share price that moves with the market. Buy the ones you believe in.' },
  { n: '2', title: 'Follow the tournaments', text: 'Watch live leaderboards as your players compete. Prices react to how they place.' },
  { n: '3', title: 'Earn dividends', text: 'When a player places well, everyone holding their shares gets paid.' },
];

/** What a logged-out visitor sees first: what Forecast is, a live look at the market, and two ways in. Deliberately short. */
export function LandingPage({ onGuest, onLogin }: { onGuest: () => void; onLogin: (mode?: 'login' | 'register') => void }) {
  const { data: movers } = useMarkets(1, 5, 'price');
  const [legal, setLegal] = useState<LegalDoc | null>(null);
  const [showEmail, setShowEmail] = useState(false);
  const [playerId, setPlayerId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const rows = movers.items.slice(0, 5);

  return (
    <div
      className="dark min-h-screen w-full flex flex-col font-sans"
      style={{ background: 'radial-gradient(ellipse at 15% 20%, rgba(0,200,255,0.06) 0%, transparent 55%), radial-gradient(ellipse at 85% 10%, rgba(155,111,255,0.07) 0%, transparent 50%), var(--background)' }}
    >
      <header className="w-full max-w-[920px] mx-auto px-6 pt-6 flex items-center">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}>
            <span className="font-mono font-bold" style={{ fontSize: 15, color: '#020610' }}>F</span>
          </div>
          <p className="font-bold tracking-wider text-foreground" style={{ fontSize: 15 }}>FORECAST</p>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[920px] mx-auto px-6">
        <section className="text-center pt-14 pb-10">
          <h1 className="font-bold text-foreground" style={{ fontSize: 'clamp(30px, 6vw, 48px)', lineHeight: 1.1, letterSpacing: '-1px' }}>
            The Fortnite Esports Stock Market
          </h1>
          <p className="text-muted-foreground mx-auto mt-4" style={{ fontSize: 'clamp(15px, 2.4vw, 18px)', maxWidth: 560, lineHeight: 1.55 }}>
            Trade pro players like stocks. Buy shares, follow live tournaments, and earn dividends when your players place.
          </p>
          <div className="flex items-center justify-center gap-3 mt-7 flex-wrap">
            <button
              onClick={onGuest}
              className="px-6 py-3 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{ fontSize: 15, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
            >
              Guest mode
            </button>
            <button onClick={() => onLogin()} className="px-6 py-3 rounded-xl font-bold border border-border text-foreground hover:bg-white/5" style={{ fontSize: 15 }}>
              Log in
            </button>
          </div>
          <p className="text-muted-foreground mt-3" style={{ fontSize: 12.5 }}>Guest mode lets you browse the market without an account.</p>
        </section>

        {rows.length > 0 && (
          <section className="rounded-2xl border border-border overflow-hidden mb-12" style={{ background: 'var(--card)' }}>
            <div className="px-5 py-3 border-b border-border flex items-center justify-between">
              <p className="font-semibold text-foreground" style={{ fontSize: 14 }}>Highest-priced players</p>
              <p className="text-muted-foreground" style={{ fontSize: 11.5 }}>Live prices</p>
            </div>
            {rows.map((m, i) => {
              const pct = toNumber(m.change_pct);
              return (
                <button key={m.id} onClick={() => setPlayerId(m.id)} className="w-full text-left flex items-center justify-between px-5 py-3 hover:bg-white/[0.03] transition-colors" style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
                  <p className="text-foreground font-semibold truncate" style={{ fontSize: 14 }}>{m.real_name || m.gamertag}</p>
                  <div className="flex items-baseline gap-4 shrink-0 font-mono">
                    <span className="text-foreground" style={{ fontSize: 14 }}>{usd(toNumber(m.last_price))}</span>
                    <span className="font-bold" style={{ fontSize: 13, minWidth: 64, textAlign: 'right', color: pct >= 0 ? 'var(--gain)' : 'var(--loss)' }}>
                      {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                    </span>
                  </div>
                </button>
              );
            })}
          </section>
        )}

        <section className="grid gap-3 sm:grid-cols-3 mb-14">
          {STEPS.map(s => (
            <div key={s.n} className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
              <span className="font-mono font-bold inline-flex items-center justify-center rounded-lg mb-3" style={{ width: 28, height: 28, fontSize: 13, background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}>{s.n}</span>
              <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>{s.title}</p>
              <p className="text-muted-foreground mt-1" style={{ fontSize: 13, lineHeight: 1.5 }}>{s.text}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="w-full max-w-[920px] mx-auto px-6 pb-8 text-center text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.7 }}>
        <p>
          <button onClick={() => setLegal('terms')} className="hover:text-foreground underline-offset-2 hover:underline" style={{ fontSize: 12 }}>Terms</button>
          {' · '}
          <button onClick={() => setLegal('privacy')} className="hover:text-foreground underline-offset-2 hover:underline" style={{ fontSize: 12 }}>Privacy</button>
          {' · '}
          <button onClick={() => setShowEmail(true)} className="hover:text-foreground underline-offset-2 hover:underline" style={{ fontSize: 12 }}>{SUPPORT_EMAIL}</button>
        </p>
        <p>A game played with virtual cash. Not affiliated with or endorsed by Epic Games.</p>
      </footer>

      {legal && <LegalModal doc={legal} onClose={() => setLegal(null)} />}
      {playerId && (
        <GuestContext.Provider value={{ isGuest: true, requireAccount: f => setPrompt(f ?? ''), goLogin: onLogin }}>
          <PlayerModal playerId={playerId} onClose={() => setPlayerId(null)} />
          {prompt !== null && <AccountPrompt feature={prompt || undefined} onClose={() => setPrompt(null)} />}
        </GuestContext.Provider>
      )}
      {showEmail && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 modal-overlay" style={{ background: 'rgba(2,6,16,0.78)' }} onClick={() => setShowEmail(false)}>
          <div className="w-full max-w-[340px] rounded-2xl border border-border p-6 text-center" style={{ background: 'var(--card)' }} onClick={e => e.stopPropagation()}>
            <p className="text-foreground font-bold" style={{ fontSize: 16 }}>Contact us</p>
            <p className="text-muted-foreground mt-1" style={{ fontSize: 12.5 }}>Questions, feedback or problems? Email us at</p>
            <p className="font-mono font-semibold text-foreground mt-2 select-all break-all" style={{ fontSize: 14 }}>{SUPPORT_EMAIL}</p>
            <button onClick={() => setShowEmail(false)} className="mt-4 px-5 py-2 rounded-xl font-semibold border border-border text-foreground hover:bg-white/5" style={{ fontSize: 13 }}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
