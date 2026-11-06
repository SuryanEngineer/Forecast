import { useEffect, useState } from 'react';
import { Menu } from 'lucide-react';
import { useCompact } from './lib/useCompact';
import { toNumber } from './lib/types';
import { useOpenOrderCount } from './components/OpenOrders';
import { AuthProvider, useAuth } from './lib/auth';
import { AuthScreen } from './components/AuthScreen';
import { LandingPage } from './components/LandingPage';
import { AccountPrompt, AccountRequired } from './components/AccountPrompt';
import { GuestContext } from './lib/guest';
import { Sidebar } from './components/Sidebar';
import { Dashboard } from './components/Dashboard';
import { Markets } from './components/Markets';
import { Portfolio } from './components/Portfolio';
import { Leaderboards } from './components/Leaderboards';
import { Tournaments } from './components/Tournaments';
import { PlayerModal } from './components/PlayerModal';
import { TeamModal } from './components/TeamModal';
import { TournamentDetailModal } from './components/TournamentDetailModal';
import { IntroTour, introSeenKey } from './components/IntroTour';
import { HelpCenter } from './components/HelpModal';
import { StatsPage } from './components/StatsPage';
import { SettingsPage } from './components/SettingsPage';
import { LegalModal, type LegalDoc } from './components/LegalModal';
import { FeedbackModal } from './components/FeedbackModal';
import type { TournamentResponse } from './lib/types';

type Page = 'dashboard' | 'markets' | 'portfolio' | 'leaderboards' | 'tournaments' | 'stats' | 'settings';

function AuthenticatedApp({ guest }: { guest?: { goLogin: (mode?: 'login' | 'register') => void } }) {
  const { user, justRegistered, wallet } = useAuth();
  const isGuest = !!guest;
  const [prompt, setPrompt] = useState<string | null>(null);
  const compact = useCompact();
  const [menuOpen, setMenuOpen] = useState(false);
  const openOrders = useOpenOrderCount();
  useEffect(() => { if (!compact) setMenuOpen(false); }, [compact]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [playerModalId, setPlayerModalId] = useState<string | null>(null);
  const [teamModalUserId, setTeamModalUserId] = useState<string | null>(null);
  const [selectedTournament, setSelectedTournament] = useState<TournamentResponse | null>(null);
  // Set when a tournament is opened from a player's profile: the standings open on that player's team.
  const [tournamentFocusPlayerId, setTournamentFocusPlayerId] = useState<string | null>(null);
  const [marketSearch, setMarketSearch] = useState('');
  const [legalDoc, setLegalDoc] = useState<LegalDoc | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);

  // Keyed per-account (introSeenKey(user.id)), not one global flag -- see
  // IntroTour.tsx. `justRegistered` (see lib/auth.tsx) is what actually
  // decides whether this starts true: it's only set for the
  // AuthenticatedApp mount immediately following a successful
  // register(), so a returning user logging in again (even on a new
  // device, where no localStorage flag exists yet) never sees the tour
  // pop up uninvited -- only the "How it works" sidebar button can
  // reopen it for them. `user` is guaranteed non-null here (see Root
  // below), and `useState(() => ...)` only reads `justRegistered` once,
  // at mount, so it can't flip back on later re-renders.
  const introKey = introSeenKey(user?.id ?? 'guest');
  const [showIntro, setShowIntro] = useState(() => justRegistered && !isGuest);
  const [introStep, setIntroStep] = useState(0);
  const [showGuide, setShowGuide] = useState(false);

  function openIntroAt(step: number) {
    setIntroStep(step);
    setShowIntro(true);
  }

  function navigate(page: string, playerId?: string) {
    if (page === 'player' && playerId) { setPlayerModalId(playerId); return; }
    setCurrentPage(page as Page);
  }

  const PAGE_TITLES: Record<string, string> = { dashboard: 'Home', markets: 'Market', portfolio: 'My Portfolio', leaderboards: 'Leaderboard', stats: 'My Stats', tournaments: 'Events', settings: 'Settings' };
  const cash = wallet ? toNumber(wallet.cash_balance) : null;
  const goTo = (page: string) => { setCurrentPage(page as Page); setMenuOpen(false); };

  const guestValue = { isGuest, requireAccount: (f?: string) => { if (isGuest) setPrompt(f ?? ''); }, goLogin: guest?.goLogin ?? (() => {}) };

  return (
    <GuestContext.Provider value={guestValue}>
    <div
      className={`dark overflow-hidden flex font-sans ${compact ? 'flex-col' : ''}`}
      style={{ height: '100dvh', background: 'radial-gradient(ellipse at 15% 50%, rgba(0,200,255,0.03) 0%, transparent 55%), radial-gradient(ellipse at 85% 15%, rgba(155,111,255,0.04) 0%, transparent 50%), var(--background)' }}
    >
      {compact ? (
        <>
          {/* Phone top bar: menu button, current page, cash */}
          <header
            className="shrink-0 flex items-center gap-2 border-b border-border px-2"
            style={{ background: 'var(--sidebar)', minHeight: 52, paddingTop: 'env(safe-area-inset-top)', paddingLeft: 'max(8px, env(safe-area-inset-left))', paddingRight: 'max(8px, env(safe-area-inset-right))' }}
          >
            <button onClick={() => setMenuOpen(true)} aria-label="Open menu" className="relative p-2.5 rounded-xl hover:bg-white/5 text-foreground">
              <Menu className="w-6 h-6" />
              {openOrders > 0 && <span className="absolute top-1.5 right-1.5 w-2.5 h-2.5 rounded-full" style={{ background: '#fbbf24' }} />}
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}>
                <span className="font-mono font-bold" style={{ fontSize: 12, color: '#020610' }}>F</span>
              </div>
              <p className="font-bold text-foreground truncate" style={{ fontSize: 15 }}>{PAGE_TITLES[currentPage] ?? 'Forecast'}</p>
            </div>
            {cash !== null && (
              <div className="ml-auto text-right shrink-0 pr-1">
                <p className="text-muted-foreground leading-none" style={{ fontSize: 9.5 }}>Cash</p>
                <p className="font-mono font-bold text-foreground leading-tight" style={{ fontSize: 14 }}>${cash.toLocaleString('en-US', { maximumFractionDigits: 0 })}</p>
              </div>
            )}
          </header>
          {menuOpen && (
            <div className="fixed inset-0 z-[80] flex" role="dialog" aria-modal="true" aria-label="Menu">
              <div className="mobile-drawer h-full">
                <Sidebar variant="drawer" currentPage={currentPage} navigate={goTo} onShowIntro={() => { setMenuOpen(false); setShowGuide(true); }} onShowLegal={doc => { setMenuOpen(false); setLegalDoc(doc); }} onShowFeedback={() => { setMenuOpen(false); setShowFeedback(true); }} onClose={() => setMenuOpen(false)} />
              </div>
              <div className="flex-1 mobile-scrim" style={{ background: 'rgba(0,0,0,0.6)' }} onClick={() => setMenuOpen(false)} />
            </div>
          )}
        </>
      ) : (
        <Sidebar currentPage={currentPage} navigate={page => setCurrentPage(page as Page)} onShowIntro={() => setShowGuide(true)} onShowLegal={setLegalDoc} onShowFeedback={() => setShowFeedback(true)} />
      )}

      <main className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent', paddingBottom: compact ? 'env(safe-area-inset-bottom)' : undefined, paddingLeft: compact ? 'env(safe-area-inset-left)' : undefined, paddingRight: compact ? 'env(safe-area-inset-right)' : undefined }}>
        {currentPage === 'dashboard' && (
          <Dashboard navigate={navigate} openPlayer={setPlayerModalId} goToMarketWithSearch={term => { setMarketSearch(term); setCurrentPage('markets'); }} />
        )}
        {currentPage === 'markets' && (
          <Markets navigate={navigate} initialSearch={marketSearch} onSearchChange={setMarketSearch} />
        )}
        {currentPage === 'portfolio' && (isGuest
          ? <AccountRequired title="My Portfolio" text="Create a free account to start with virtual cash, buy shares, and track everything you own here." />
          : <Portfolio navigate={navigate} openPlayer={setPlayerModalId} />)}
        {currentPage === 'leaderboards' && <Leaderboards openPlayer={setPlayerModalId} openTeam={setTeamModalUserId} />}
        {currentPage === 'stats' && (isGuest ? <AccountRequired title="My Stats" text="Your trading history, earnings and records show up here once you have an account." /> : <StatsPage />)}
        {currentPage === 'settings' && (isGuest ? <AccountRequired title="Settings" text="Create an account to manage your profile and settings." /> : <SettingsPage />)}
        {currentPage === 'tournaments' && <Tournaments navigate={navigate} openTournament={t => { setTournamentFocusPlayerId(null); setSelectedTournament(t); }} />}
      </main>

      {playerModalId && (
        <PlayerModal
          playerId={playerModalId}
          onClose={() => setPlayerModalId(null)}
          onOpenTournament={(tournament, focusPlayerId) => {
            setPlayerModalId(null);
            setTournamentFocusPlayerId(focusPlayerId);
            setSelectedTournament(tournament);
          }}
        />
      )}
      {teamModalUserId && <TeamModal userId={teamModalUserId} onClose={() => setTeamModalUserId(null)} />}
      {selectedTournament && (
        <TournamentDetailModal
          tournament={selectedTournament}
          focusPlayerId={tournamentFocusPlayerId ?? undefined}
          onClose={() => { setSelectedTournament(null); setTournamentFocusPlayerId(null); }}
          onOpenPlayer={id => { setSelectedTournament(null); setTournamentFocusPlayerId(null); setPlayerModalId(id); }}
        />
      )}
      {legalDoc && <LegalModal doc={legalDoc} onClose={() => setLegalDoc(null)} />}
      {showFeedback && <FeedbackModal onClose={() => setShowFeedback(false)} />}
      {showIntro && (
        <IntroTour
          initialStep={introStep}
          storageKey={introKey}
          onClose={() => { setShowIntro(false); setIntroStep(0); }}
          onNavigate={page => setCurrentPage(page as Page)}
          onOpenGuide={() => { setShowIntro(false); setIntroStep(0); setShowGuide(true); }}
        />
      )}
      {showGuide && (
        <HelpCenter
          onClose={() => setShowGuide(false)}
          onReplayTour={() => { setShowGuide(false); openIntroAt(0); }}
        />
      )}
      {prompt !== null && <AccountPrompt feature={prompt || undefined} onClose={() => setPrompt(null)} />}
    </div>
    </GuestContext.Provider>
  );
}

function Root() {
  const { isAuthenticated, isLoading } = useAuth();
  // Logged-out visitors start on the landing page; from there they can browse as a guest or log in.
  const [screen, setScreen] = useState<'landing' | 'login' | 'register' | 'guest'>('landing');

  if (isLoading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center" style={{ background: 'var(--background)' }}>
        <p className="text-muted-foreground" style={{ fontSize: 14 }}>Loading…</p>
      </div>
    );
  }

  if (isAuthenticated) return <AuthenticatedApp />;
  if (screen === 'login' || screen === 'register') return <AuthScreen initialMode={screen} onBack={() => setScreen('landing')} />;
  if (screen === 'guest') return <AuthenticatedApp guest={{ goLogin: (mode = 'login') => setScreen(mode) }} />;
  return <LandingPage onGuest={() => setScreen('guest')} onLogin={() => setScreen('login')} />;
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}
