import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Markets } from './Markets';
import { Leaderboards } from './Leaderboards';
import { Tournaments } from './Tournaments';
import { PlayerModal } from './PlayerModal';
import { TournamentDetailModal } from './TournamentDetailModal';
import type { TournamentResponse } from '../lib/types';

type Page = 'markets' | 'leaderboards' | 'tournaments';
const TABS: { key: Page; label: string }[] = [
  { key: 'markets', label: 'Market' },
  { key: 'leaderboards', label: 'Leaderboard' },
  { key: 'tournaments', label: 'Events' },
];

/** Guest mode: look around the market, leaderboard and events with no account. Everything is read-only; trading and
 * personal pages need a login, which is one tap away in the top bar. */
export function GuestApp({ onLogin, onBack }: { onLogin: () => void; onBack: () => void }) {
  const [page, setPage] = useState<Page>('markets');
  const [playerId, setPlayerId] = useState<string | null>(null);
  const [tournament, setTournament] = useState<TournamentResponse | null>(null);
  const [focusPlayerId, setFocusPlayerId] = useState<string | null>(null);
  const [marketSearch, setMarketSearch] = useState('');
  const [notice, setNotice] = useState<string | null>(null);

  function navigate(target: string, id?: string) {
    if (target === 'player' && id) { setPlayerId(id); return; }
    if (TABS.some(t => t.key === target)) setPage(target as Page);
    else setNotice('That page needs an account. Log in to use it.');
  }

  return (
    <div className="dark flex flex-col font-sans" style={{ height: '100dvh', background: 'var(--background)' }}>
      <header className="shrink-0 flex items-center gap-3 border-b border-border px-3 sm:px-5" style={{ background: 'var(--sidebar)', minHeight: 56 }}>
        <button onClick={onBack} aria-label="Back" className="p-2 rounded-xl hover:bg-white/5 text-muted-foreground"><ArrowLeft className="w-5 h-5" /></button>
        <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}>
          <span className="font-mono font-bold" style={{ fontSize: 12, color: '#020610' }}>F</span>
        </div>
        <nav className="flex items-center gap-1 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => { setPage(t.key); setNotice(null); }}
              className="px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap transition-colors"
              style={{ fontSize: 13.5, background: page === t.key ? 'rgba(0,200,255,0.12)' : 'transparent', color: page === t.key ? 'var(--primary)' : 'var(--muted-foreground)' }}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <span className="hidden sm:inline text-muted-foreground ml-1" style={{ fontSize: 12 }}>Guest mode</span>
        <button onClick={onLogin} className="ml-auto px-4 py-2 rounded-xl font-bold shrink-0" style={{ fontSize: 13, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}>
          Log in
        </button>
      </header>

      {notice && (
        <div className="shrink-0 px-5 py-2 text-center" style={{ fontSize: 12.5, background: 'rgba(251,191,36,0.1)', color: '#fbbf24' }}>
          {notice}
        </div>
      )}

      <main className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}>
        {page === 'markets' && <Markets navigate={navigate} initialSearch={marketSearch} onSearchChange={setMarketSearch} />}
        {page === 'leaderboards' && <Leaderboards openPlayer={setPlayerId} openTeam={() => setNotice("Log in to look at other investors' portfolios.")} />}
        {page === 'tournaments' && <Tournaments navigate={navigate} openTournament={t => { setFocusPlayerId(null); setTournament(t); }} />}
      </main>

      {playerId && (
        <PlayerModal
          playerId={playerId}
          readOnly
          onLogin={onLogin}
          onClose={() => setPlayerId(null)}
          onOpenTournament={(t, focus) => { setPlayerId(null); setFocusPlayerId(focus); setTournament(t); }}
        />
      )}
      {tournament && (
        <TournamentDetailModal
          tournament={tournament}
          focusPlayerId={focusPlayerId ?? undefined}
          onClose={() => { setTournament(null); setFocusPlayerId(null); }}
          onOpenPlayer={id => { setTournament(null); setFocusPlayerId(null); setPlayerId(id); }}
        />
      )}
    </div>
  );
}
