import { useState } from 'react';
import { AuthProvider, useAuth } from './lib/auth';
import { AuthScreen } from './components/AuthScreen';
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
import { StatsPage } from './components/StatsPage';
import { SettingsPage } from './components/SettingsPage';
import { LegalModal, type LegalDoc } from './components/LegalModal';
import type { TournamentResponse } from './lib/types';

type Page = 'dashboard' | 'markets' | 'portfolio' | 'leaderboards' | 'tournaments' | 'stats' | 'settings';

function AuthenticatedApp() {
  const { user, justRegistered } = useAuth();
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [playerModalId, setPlayerModalId] = useState<string | null>(null);
  const [teamModalUserId, setTeamModalUserId] = useState<string | null>(null);
  const [selectedTournament, setSelectedTournament] = useState<TournamentResponse | null>(null);
  // Set when a tournament is opened from a player's profile: the standings open on that player's team.
  const [tournamentFocusPlayerId, setTournamentFocusPlayerId] = useState<string | null>(null);
  const [marketSearch, setMarketSearch] = useState('');
  const [legalDoc, setLegalDoc] = useState<LegalDoc | null>(null);

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
  const introKey = introSeenKey(user!.id);
  const [showIntro, setShowIntro] = useState(() => justRegistered);
  const [introStep, setIntroStep] = useState(0);

  function openIntroAt(step: number) {
    setIntroStep(step);
    setShowIntro(true);
  }

  function navigate(page: string, playerId?: string) {
    if (page === 'player' && playerId) { setPlayerModalId(playerId); return; }
    setCurrentPage(page as Page);
  }

  return (
    <div
      className="dark h-screen overflow-hidden flex font-sans"
      style={{ background: 'radial-gradient(ellipse at 15% 50%, rgba(0,200,255,0.03) 0%, transparent 55%), radial-gradient(ellipse at 85% 15%, rgba(155,111,255,0.04) 0%, transparent 50%), var(--background)' }}
    >
      <Sidebar currentPage={currentPage} navigate={page => setCurrentPage(page as Page)} onShowIntro={() => openIntroAt(0)} onShowLegal={setLegalDoc} />

      <main className="flex-1 overflow-y-auto" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}>
        {currentPage === 'dashboard' && (
          <Dashboard navigate={navigate} openPlayer={setPlayerModalId} goToMarketWithSearch={term => { setMarketSearch(term); setCurrentPage('markets'); }} />
        )}
        {currentPage === 'markets' && (
          <Markets navigate={navigate} initialSearch={marketSearch} onSearchChange={setMarketSearch} />
        )}
        {currentPage === 'portfolio' && (
          <Portfolio navigate={navigate} openPlayer={setPlayerModalId} />
        )}
        {currentPage === 'leaderboards' && <Leaderboards openPlayer={setPlayerModalId} openTeam={setTeamModalUserId} />}
        {currentPage === 'stats' && <StatsPage />}
        {currentPage === 'settings' && <SettingsPage />}
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
      {showIntro && (
        <IntroTour
          initialStep={introStep}
          storageKey={introKey}
          onClose={() => { setShowIntro(false); setIntroStep(0); }}
        />
      )}
    </div>
  );
}

function Root() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center" style={{ background: 'var(--background)' }}>
        <p className="text-muted-foreground" style={{ fontSize: 14 }}>Loading…</p>
      </div>
    );
  }

  return isAuthenticated ? <AuthenticatedApp /> : <AuthScreen />;
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}
