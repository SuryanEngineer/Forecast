import { useState, useEffect } from 'react';
import { Calendar, ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../lib/api';
import { useTournamentCalendar, useTournamentsList } from '../lib/hooks';
import { toNumber, type CalendarTournamentResponse, type TournamentResponse } from '../lib/types';
import { LiveLeaderboard } from './LiveLeaderboard';
import { HelpButton } from './HelpModal';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openTournament: (tournament: TournamentResponse) => void;
}

interface PlacementResult {
  id: string;
  tournament_id: string;
  player_id: string;
  placement: number;
  points: string | number | null;
  prize_won: string | number | null;
  eliminations: number | null;
}

function useCountdown(targetDate: string | null) {
  const [t, setT] = useState({ d: 0, h: 0, m: 0, s: 0 });
  useEffect(() => {
    if (!targetDate) return;
    const update = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) { setT({ d: 0, h: 0, m: 0, s: 0 }); return; }
      setT({
        d: Math.floor(diff / 86400000),
        h: Math.floor((diff % 86400000) / 3600000),
        m: Math.floor((diff % 3600000) / 60000),
        s: Math.floor((diff % 60000) / 1000),
      });
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [targetDate]);
  return t;
}

function CountdownBox({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="w-14 h-14 rounded-2xl flex items-center justify-center font-mono font-bold" style={{ fontSize: 22, background: 'var(--muted)', border: '1.5px solid var(--border)', color: 'var(--primary)' }}>
        {String(value).padStart(2, '0')}
      </div>
      <p className="text-muted-foreground uppercase" style={{ fontSize: 10, letterSpacing: '0.1em' }}>{label}</p>
    </div>
  );
}

function FeaturedEvent({ tournament, onOpen }: { tournament: TournamentResponse; onOpen: () => void }) {
  const cd = useCountdown(tournament.start_time);
  const prizePool = toNumber(tournament.prize_pool);
  return (
    <div className="rounded-2xl border p-6" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.07), rgba(155,111,255,0.05)), var(--card)', borderColor: 'rgba(0,200,255,0.25)' }}>
      <button onClick={onOpen} className="w-full text-left">
      <div className="flex items-start gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>NEXT EVENT</span>
            <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>
              {tournament.tournament_type.replace('_', ' ')}
            </span>
          </div>
          <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournament.name}</h2>
          {tournament.region && <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>{tournament.region}</p>}
        </div>
        {prizePool > 0 && (
          <div className="text-right ml-auto shrink-0">
            <p className="font-mono font-bold" style={{ fontSize: 26, color: 'var(--gain)' }}>${prizePool.toLocaleString()}</p>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>total prize pool</p>
          </div>
        )}
      </div>
      </button>

      {tournament.start_time && (
        <div className="flex flex-wrap gap-4 mb-5 text-muted-foreground" style={{ fontSize: 13 }}>
          <span className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4" />
            {new Date(tournament.start_time).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
          </span>
        </div>
      )}

      {tournament.start_time && (
        <div>
          <p className="text-muted-foreground mb-3" style={{ fontSize: 13 }}>Starts in:</p>
          <div className="flex items-center gap-3">
            <CountdownBox value={cd.d} label="days" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 22, paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.h} label="hours" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 22, paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.m} label="min" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 22, paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.s} label="sec" />
          </div>
        </div>
      )}

      <div className="mt-4 p-3 rounded-xl" style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
        <p style={{ fontSize: 13, color: '#fbbf24', lineHeight: 1.6 }}>
          💡 <strong>Tip:</strong> Owning shares in players who place well earns you a dividend once results are finalized. Buy shares before big events!
        </p>
      </div>
    </div>
  );
}

function UpcomingSmall({ tournament, onOpen }: { tournament: TournamentResponse; onOpen: () => void }) {
  const daysLeft = tournament.start_time ? Math.ceil((new Date(tournament.start_time).getTime() - Date.now()) / 86400000) : null;
  const prizePool = toNumber(tournament.prize_pool);
  return (
    <button onClick={onOpen} className="w-full rounded-2xl border border-border p-4 text-left transition-colors hover:bg-white/[0.03]" style={{ background: 'var(--card)' }}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <p className="text-foreground font-semibold" style={{ fontSize: 14 }}>{tournament.name}</p>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12 }}>
            {tournament.tournament_type.replace('_', ' ')}
            {tournament.start_time ? ` · ${new Date(tournament.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : ''}
          </p>
        </div>
        {daysLeft !== null && (
          <span className="font-mono font-bold px-2.5 py-1 rounded-xl shrink-0" style={{ fontSize: 13, background: daysLeft <= 7 ? 'rgba(251,191,36,0.15)' : 'rgba(0,200,255,0.1)', color: daysLeft <= 7 ? '#fbbf24' : 'var(--primary)' }}>
            {daysLeft}d
          </span>
        )}
      </div>
      {prizePool > 0 && (
        <p className="text-muted-foreground mt-2" style={{ fontSize: 12 }}>${prizePool.toLocaleString()} prize pool</p>
      )}
    </button>
  );
}

function ResultCard({ tournament, onOpenDetail }: { tournament: TournamentResponse; onOpenDetail: () => void }) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<PlacementResult[] | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && results === null) {
      try {
        const r = await api.get<PlacementResult[]>(`/tournaments/${tournament.id}/results`);
        setResults(r);
      } catch {
        setResults([]);
      }
    }
  }

  const prizePool = toNumber(tournament.prize_pool);

  return (
    <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
      <button onClick={toggle} className="w-full flex items-center gap-4 p-4 text-left hover:bg-white/[0.03] transition-colors">
        <div className="flex-1">
          <p className="text-foreground font-semibold" style={{ fontSize: 14 }}>{tournament.name}</p>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12 }}>
            {tournament.tournament_type.replace('_', ' ')}
            {tournament.start_time ? ` · ${new Date(tournament.start_time).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}` : ''}
          </p>
        </div>
        {prizePool > 0 && (
          <p className="font-mono font-bold" style={{ fontSize: 16, color: 'var(--gain)', whiteSpace: 'nowrap' }}>${prizePool.toLocaleString()}</p>
        )}
        {open ? <ChevronUp className="w-5 h-5 text-muted-foreground shrink-0" /> : <ChevronDown className="w-5 h-5 text-muted-foreground shrink-0" />}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-border pt-3 space-y-2">
          <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>Placements</p>
          {results === null ? (
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>Loading…</p>
          ) : results.length === 0 ? (
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>No results entered yet.</p>
          ) : (
            results.map(r => (
              <div key={r.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ background: 'var(--muted)' }}>
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                  style={{
                    fontSize: 12,
                    background: r.placement === 1 ? 'rgba(251,191,36,0.2)' : r.placement === 2 ? 'rgba(156,163,175,0.15)' : r.placement === 3 ? 'rgba(205,127,50,0.15)' : 'rgba(255,255,255,0.06)',
                    color: r.placement === 1 ? '#fbbf24' : r.placement === 2 ? '#9ca3af' : r.placement === 3 ? '#cd7f32' : 'var(--muted-foreground)',
                  }}
                >
                  #{r.placement}
                </div>
                <div className="flex-1">
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>{r.points !== null ? `${toNumber(r.points)} pts` : ''}</p>
                </div>
                {r.prize_won !== null && (
                  <p className="font-mono font-bold" style={{ fontSize: 14, color: 'var(--gain)' }}>${toNumber(r.prize_won).toLocaleString()}</p>
                )}
              </div>
            ))
          )}
          <button
            onClick={onOpenDetail}
            className="w-full text-center py-2 rounded-xl font-semibold transition-colors hover:bg-white/[0.03]"
            style={{ fontSize: 12.5, color: 'var(--primary)' }}
          >
            Full details &amp; per-share dividend payouts →
          </button>
        </div>
      )}
    </div>
  );
}

const TIER_LABELS: Record<string, string> = {
  cash_cup: 'Cash Cup',
  fncs_qualifier: 'FNCS Qualifier',
  fncs_finals: 'FNCS Finals',
  global_championship: 'Global / EWC',
  major: 'Major',
  other: 'Other',
};

function CalendarRow({ tournament, onOpen }: { tournament: CalendarTournamentResponse; onOpen: () => void }) {
  const pool = tournament.total_dividend_pool !== null ? toNumber(tournament.total_dividend_pool) : null;
  const isLive = tournament.status === 'results_pending';
  const dateLabel = tournament.start_time
    ? new Date(tournament.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : 'TBD';

  return (
    <button
      onClick={onOpen}
      className="w-full flex items-center gap-3 p-3.5 rounded-2xl border border-border text-left transition-colors hover:bg-white/[0.03]"
      style={{ background: 'var(--card)' }}
    >
      <div className="flex flex-col items-center justify-center rounded-xl shrink-0" style={{ width: 52, height: 44, background: 'var(--muted)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 12.5, color: 'var(--foreground)' }}>{dateLabel}</p>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{tournament.name}</p>
          {isLive && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(255,71,87,0.15)', color: '#ff4757' }}>
              ● Live
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11.5 }}>
          {TIER_LABELS[tournament.tournament_type] ?? tournament.tournament_type}
          {tournament.region ? ` · ${tournament.region}` : ''}
        </p>
      </div>

      <div className="text-right shrink-0">
        {pool !== null && pool > 0 ? (
          <>
            <p className="font-mono font-bold" style={{ fontSize: 13.5, color: 'var(--gain)' }}>${pool.toLocaleString()}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>total dividend pool</p>
          </>
        ) : (
          <p className="text-muted-foreground italic" style={{ fontSize: 11.5 }}>Pool TBD</p>
        )}
      </div>
    </button>
  );
}

function TournamentCalendar({ openTournament }: { openTournament: (t: TournamentResponse) => void }) {
  const { data: calendar, loading } = useTournamentCalendar();

  if (loading && calendar.length === 0) {
    return <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading calendar…</p>;
  }
  if (calendar.length === 0) {
    return <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No upcoming tournaments tracked yet — new ones are picked up automatically.</p>;
  }

  return (
    <div className="space-y-2.5">
      <p className="text-muted-foreground" style={{ fontSize: 12 }}>
        Updates automatically as tournaments are tracked and results come in.
      </p>
      {calendar.map(t => (
        <CalendarRow
          key={t.id}
          tournament={t}
          onOpen={() =>
            openTournament({
              id: t.id,
              name: t.name,
              tournament_type: t.tournament_type,
              region: t.region,
              start_time: t.start_time,
              end_time: t.end_time,
              prize_pool: null,
              status: t.status,
              created_at: t.start_time ?? new Date().toISOString(),
            })
          }
        />
      ))}
    </div>
  );
}

export function Tournaments({ openTournament }: Props) {
  const { data: tournaments, loading } = useTournamentsList();
  const [tab, setTab] = useState<'upcoming' | 'calendar' | 'results'>('upcoming');

  const upcoming = tournaments.filter(t => t.status === 'scheduled' || t.status === 'results_pending');
  const finalized = tournaments.filter(t => t.status === 'finalized');
  const inProgress = tournaments.filter(t => t.status === 'results_pending');
  const [featured, ...otherUpcoming] = upcoming;

  return (
    <div className="p-6 max-w-[900px] mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-1.5">
          <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Tournaments</h1>
          <HelpButton topic="tournaments" size={17} />
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Own the right players when results come in to earn dividends.
        </p>
      </div>

      <div className="flex rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
        {[
          { key: 'upcoming' as const, label: `⏳ Upcoming (${upcoming.length})` },
          { key: 'calendar' as const, label: `📅 Calendar` },
          { key: 'results' as const, label: `🏁 Results (${finalized.length})` },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="flex-1 py-3 font-semibold transition-all"
            style={{ fontSize: 14, background: tab === t.key ? 'rgba(0,200,255,0.1)' : 'transparent', color: tab === t.key ? 'var(--primary)' : 'var(--muted-foreground)' }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {inProgress.length > 0 && (
        <div>
          <p className="font-bold mb-3" style={{ fontSize: 15, color: '#ff4757' }}>● Happening Now</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {inProgress.map(t => (
              <div key={t.id} className="rounded-2xl border border-border p-4" style={{ background: 'var(--card)' }}>
                <LiveLeaderboard tournamentId={t.id} />
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'calendar' ? (
        <TournamentCalendar openTournament={openTournament} />
      ) : loading && tournaments.length === 0 ? (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading tournaments…</p>
      ) : tab === 'upcoming' ? (
        <div className="space-y-4">
          {featured && <FeaturedEvent tournament={featured} onOpen={() => openTournament(featured)} />}
          {!featured && <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No upcoming tournaments scheduled.</p>}
          {otherUpcoming.length > 0 && (
            <div>
              <p className="text-muted-foreground font-medium mb-3" style={{ fontSize: 14 }}>Also coming up</p>
              <div className="space-y-3">
                {otherUpcoming.map(t => <UpcomingSmall key={t.id} tournament={t} onOpen={() => openTournament(t)} />)}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {finalized.length === 0 && <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No finalized tournaments yet.</p>}
          {finalized.map(t => <ResultCard key={t.id} tournament={t} onOpenDetail={() => openTournament(t)} />)}
        </div>
      )}
    </div>
  );
}
