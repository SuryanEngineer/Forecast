import React, { useState, useEffect } from 'react';
import { Calendar } from 'lucide-react';
import { tournamentDisplayName } from '../lib/tournamentName';
import { useAnnouncedTournaments, useTournamentCalendar } from '../lib/hooks';
import {
  toNumber,
  type AnnouncedTournament,
  type CalendarTournamentResponse,
  type TournamentResponse,
} from '../lib/types';
import { LiveLeaderboard } from './LiveLeaderboard';
import { HelpButton } from './HelpModal';
import { OpenRoundsSection } from './OpenRounds';
import { usd } from '../lib/format';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openTournament: (tournament: TournamentResponse) => void;
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
      <div className="rounded-2xl flex items-center justify-center font-mono font-bold" style={{ width: 'clamp(38px, 12.5vw, 56px)', height: 'clamp(38px, 12.5vw, 56px)', fontSize: 'clamp(16px, 5vw, 22px)', background: 'var(--muted)', border: '1.5px solid var(--border)', color: 'var(--primary)' }}>
        {String(value).padStart(2, '0')}
      </div>
      <p className="text-muted-foreground uppercase" style={{ fontSize: 10, letterSpacing: '0.1em' }}>{label}</p>
    </div>
  );
}

const TYPE_PILL = (type: string) => type.replace(/_/g, ' ');

/** The big card at the top of the calendar: the next event to start, with a countdown. */
function FeaturedEvent({ name, type, region, startTime, pool, note, onOpen }: {
  name: string; type: string; region: string | null; startTime: string | null; pool: number | null; note?: string; onOpen?: () => void;
}) {
  const cd = useCountdown(startTime);
  const Head = (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-2 mb-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>NEXT EVENT</span>
          <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>{TYPE_PILL(type)}</span>
        </div>
        <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournamentDisplayName(name, region)}</h2>
        {region && <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>{region}</p>}
      </div>
      {pool !== null && pool > 0 && (
        <div className="text-right ml-auto shrink-0">
          <p className="font-mono font-bold" style={{ fontSize: 26, color: 'var(--gain)' }}>{usd(pool)}</p>
          <p className="text-muted-foreground" style={{ fontSize: 12 }}>total dividend pool</p>
        </div>
      )}
    </div>
  );
  return (
    <div className="rounded-2xl border p-4 sm:p-6" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.07), rgba(155,111,255,0.05)), var(--card)', borderColor: 'rgba(0,200,255,0.25)' }}>
      {onOpen ? <button onClick={onOpen} className="w-full text-left">{Head}</button> : Head}

      {startTime && (
        <div className="flex flex-wrap gap-4 mb-5 text-muted-foreground" style={{ fontSize: 13 }}>
          <span className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4" />
            {new Date(startTime).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
          </span>
        </div>
      )}

      {startTime && (
        <div>
          <p className="text-muted-foreground mb-3" style={{ fontSize: 13 }}>Starts in:</p>
          <div className="flex items-center gap-1.5 sm:gap-3">
            <CountdownBox value={cd.d} label="days" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.h} label="hours" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.m} label="min" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.s} label="sec" />
          </div>
        </div>
      )}
      {note && <p className="text-muted-foreground mt-3" style={{ fontSize: 12 }}>{note}</p>}

      <div className="mt-4 p-3 rounded-xl" style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
        <p style={{ fontSize: 13, color: '#fbbf24', lineHeight: 1.6 }}>
          💡 <strong>Tip:</strong> Owning shares in players who place well earns you a dividend once results are finalized. Buy shares before big events!
        </p>
      </div>
    </div>
  );
}

/** Same card, in red, for an event that is running right now, with the top of its live leaderboard. */
function LiveEvent({ tournament, onOpen }: { tournament: CalendarTournamentResponse; onOpen: () => void }) {
  const pool = tournament.total_dividend_pool !== null ? toNumber(tournament.total_dividend_pool) : null;
  return (
    <div className="rounded-2xl border p-6" style={{ background: 'linear-gradient(135deg, rgba(255,71,87,0.09), rgba(155,111,255,0.04)), var(--card)', borderColor: 'rgba(255,71,87,0.4)' }}>
      <button onClick={onOpen} className="w-full text-left">
        <div className="flex items-start gap-3 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(255,71,87,0.15)', color: '#ff4757' }}>● LIVE</span>
              <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>{TYPE_PILL(tournament.tournament_type)}</span>
            </div>
            <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournamentDisplayName(tournament.name, tournament.region)}</h2>
            {tournament.region && <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>{tournament.region}</p>}
          </div>
          {pool !== null && pool > 0 && (
            <div className="text-right ml-auto shrink-0">
              <p className="font-mono font-bold" style={{ fontSize: 26, color: 'var(--gain)' }}>{usd(pool)}</p>
              <p className="text-muted-foreground" style={{ fontSize: 12 }}>total dividend pool</p>
            </div>
          )}
        </div>
        <LiveLeaderboard tournamentId={tournament.id} compact />
        <p className="text-center mt-3" style={{ fontSize: 12, color: 'var(--primary)' }}>View full leaderboard →</p>
      </button>
    </div>
  );
}

const TIER_LABELS: Record<string, string> = {
  cash_cup: 'Cash Cup',
  fncs_qualifier: 'FNCS Qualifier',
  fncs_finals: 'FNCS Finals',
  global_championship: 'Global / EWC',
  major: 'Major',
  performance_eval: 'Performance Eval',
  other: 'Other',
};

function CalendarRow({ tournament, onOpen }: { tournament: CalendarTournamentResponse; onOpen: () => void }) {
  const pool = tournament.total_dividend_pool !== null ? toNumber(tournament.total_dividend_pool) : null;
  // `phase` is computed server-side from status + start_time + end_time
  // (see the backend's app/schemas/tournament.py compute_tournament_phase)
  // -- a single source of truth instead of re-deriving "is this live" here
  // from raw status/time fields, which used to disagree with how
  // LiveLeaderboard.tsx and the Tournaments tab filters derived the same
  // thing, producing contradictory badges (e.g. "Awaiting Results" on a
  // tournament that hadn't even started yet).
  const isLive = tournament.phase === 'live';
  const isFinalizing = tournament.phase === 'finalizing';
  const isCompleted = tournament.phase === 'completed';
  // No explicit `timeZone` option -- Date/toLocaleDateString/toLocaleTimeString
  // default to the browser's own local timezone, so this automatically
  // shows each viewer their own local date/time with no extra plumbing.
  const startDate = tournament.start_time ? new Date(tournament.start_time) : null;
  const dateLabel = startDate ? startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'TBD';
  const timeLabel = startDate ? startDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null;

  return (
    <button
      onClick={onOpen}
      className="w-full flex items-center gap-3 p-3.5 rounded-2xl border border-border text-left transition-colors hover:bg-white/[0.03]"
      style={{ background: 'var(--card)' }}
    >
      <div className="flex flex-col items-center justify-center rounded-xl shrink-0" style={{ width: 60, height: 44, background: 'var(--muted)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 12, color: 'var(--foreground)', lineHeight: 1.2 }}>{dateLabel}</p>
        {timeLabel && <p className="font-mono" style={{ fontSize: 9.5, color: 'var(--muted-foreground)', lineHeight: 1.2 }}>{timeLabel}</p>}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{tournamentDisplayName(tournament.name, tournament.region)}</p>
          {isLive && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(255,71,87,0.15)', color: '#ff4757' }}>
              ● Live
            </span>
          )}
          {isCompleted && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(0,214,143,0.15)', color: '#00d68f' }}>
              ✓ Completed
            </span>
          )}
          {isFinalizing && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(255,171,64,0.15)', color: '#ffab40' }}>
              ⏳ Finalizing Results
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11.5 }}>
          {TIER_LABELS[tournament.tournament_type] ?? tournament.tournament_type}
          {tournament.region ? ` · ${tournament.region}` : ''}
          {tournament.entrant_count > 0 ? ` · ${tournament.entrant_count} qualified` : ''}
        </p>
      </div>

      <div className="text-right shrink-0">
        {pool !== null && pool > 0 ? (
          <>
            <p className="font-mono font-bold" style={{ fontSize: 13.5, color: 'var(--gain)' }}>{usd(pool)}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>total dividend pool</p>
          </>
        ) : (
          <p className="text-muted-foreground italic" style={{ fontSize: 11.5 }}>Pool TBD</p>
        )}
      </div>
    </button>
  );
}

/** An announced event that isn't a tracked tournament yet. It turns into a normal row (with live standings) on its own
 * once its payout details are published. */
function AnnouncedRow({ event }: { event: AnnouncedTournament }) {
  const pool = event.total_dividend_pool !== null ? toNumber(event.total_dividend_pool) : null;
  const startDate = event.start_time ? new Date(event.start_time) : null;
  const dateLabel = startDate ? startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'TBD';
  const timeLabel = startDate ? startDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null;
  return (
    <div className="w-full flex items-center gap-3 p-3.5 rounded-2xl border border-border text-left" style={{ background: 'var(--card)' }}>
      <div className="flex flex-col items-center justify-center rounded-xl shrink-0" style={{ width: 60, height: 44, background: 'var(--muted)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 12, color: 'var(--foreground)', lineHeight: 1.2 }}>{dateLabel}</p>
        {timeLabel && <p className="font-mono" style={{ fontSize: 9.5, color: 'var(--muted-foreground)', lineHeight: 1.2 }}>{timeLabel}</p>}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{tournamentDisplayName(event.name, event.region)}</p>
          <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}>
            Announced
          </span>
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11.5 }}>
          {TIER_LABELS[event.tournament_type] ?? event.tournament_type}
          {event.region ? ` · ${event.region}` : ''}
          {!event.finals_confirmed ? ' · date may change (Finals not published yet)' : ''}
        </p>
      </div>
      <div className="text-right shrink-0">
        {pool !== null && pool > 0 ? (
          <>
            <p className="font-mono font-bold" style={{ fontSize: 13.5, color: 'var(--gain)' }}>{usd(pool)}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>projected pool</p>
          </>
        ) : (
          <p className="text-muted-foreground italic" style={{ fontSize: 11.5 }}>Pool TBD</p>
        )}
      </div>
    </div>
  );
}

const startMs = (iso: string | null) => (iso ? new Date(iso).getTime() : Number.POSITIVE_INFINITY);

const calendarToTournament = (t: CalendarTournamentResponse): TournamentResponse => ({
  id: t.id, name: t.name, tournament_type: t.tournament_type, region: t.region, start_time: t.start_time, end_time: t.end_time,
  prize_pool: t.total_dividend_pool, status: t.status, phase: t.phase, created_at: t.start_time ?? new Date().toISOString(),
});

/** The top of the Events page, reusable elsewhere (the landing page): live events with their leaderboard in red, or, when
 * nothing is live, the next event with its countdown. Same cards, same rules as the Events page. */
export function NextEventSection({ openTournament }: { openTournament: (tournament: TournamentResponse) => void }) {
  const { data: calendar } = useTournamentCalendar(true);
  const { data: announced } = useAnnouncedTournaments();
  const live = calendar.filter(t => t.phase === 'live' || t.phase === 'finalizing').sort((a, b) => startMs(a.start_time) - startMs(b.start_time));
  const lastCompleted = calendar.filter(t => t.phase === 'completed').sort((a, b) => startMs(b.start_time) - startMs(a.start_time))[0];
  const lastCard = lastCompleted && (
    <div className="space-y-2.5">
      <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Last completed event</p>
      <CalendarRow tournament={lastCompleted} onOpen={() => openTournament(calendarToTournament(lastCompleted))} />
    </div>
  );
  if (live.length > 0) {
    return <div className="space-y-4">{live.map(t => <LiveEvent key={t.id} tournament={t} onOpen={() => openTournament(calendarToTournament(t))} />)}{lastCard}</div>;
  }
  const upcoming = [
    ...calendar.filter(t => t.phase === 'upcoming').map(t => ({ start: startMs(t.start_time), tracked: t, announced: undefined as AnnouncedTournament | undefined })),
    ...announced.map(e => ({ start: startMs(e.start_time), tracked: undefined as CalendarTournamentResponse | undefined, announced: e })),
  ].sort((a, b) => a.start - b.start);
  const next = upcoming[0];
  if (!next) return lastCard ? <div>{lastCard}</div> : null;
  const nextCard = next.tracked ? (
    <FeaturedEvent
      name={next.tracked.name} type={next.tracked.tournament_type} region={next.tracked.region} startTime={next.tracked.start_time}
      pool={next.tracked.total_dividend_pool !== null ? toNumber(next.tracked.total_dividend_pool) : null}
      onOpen={() => openTournament(calendarToTournament(next.tracked!))}
    />
  ) : (
    <FeaturedEvent
      name={next.announced!.name} type={next.announced!.tournament_type} region={next.announced!.region} startTime={next.announced!.start_time}
      pool={next.announced!.total_dividend_pool !== null ? toNumber(next.announced!.total_dividend_pool) : null}
      note={!next.announced!.finals_confirmed ? 'Announced: the date may change until the Finals are published.' : undefined}
    />
  );
  return <div className="space-y-4">{nextCard}{lastCard}</div>;
}

export function Tournaments({ openTournament }: Props) {
  // One calendar: live events first (red), then the next event (big card), then everything else still to come in date
  // order, then events awaiting final results, then completed events (newest first).
  const { data: calendar, loading } = useTournamentCalendar(true);
  const { data: announced } = useAnnouncedTournaments();

  const toTournament = (t: CalendarTournamentResponse): TournamentResponse => ({
    id: t.id,
    name: t.name,
    tournament_type: t.tournament_type,
    region: t.region,
    start_time: t.start_time,
    end_time: t.end_time,
    prize_pool: t.total_dividend_pool,
    status: t.status,
    phase: t.phase,
    created_at: t.start_time ?? new Date().toISOString(),
  });

  type Upcoming = { key: string; start: number; tracked?: CalendarTournamentResponse; announced?: AnnouncedTournament };
  // "Finalizing" (started, results still being confirmed) counts as live: same card, blank leaderboard until results arrive.
  const live = calendar.filter(t => t.phase === 'live' || t.phase === 'finalizing').sort((a, b) => startMs(a.start_time) - startMs(b.start_time));
  const completed = calendar.filter(t => t.phase === 'completed').sort((a, b) => startMs(b.start_time) - startMs(a.start_time));
  const upcoming: Upcoming[] = [
    ...calendar.filter(t => t.phase === 'upcoming').map(t => ({ key: t.id, start: startMs(t.start_time), tracked: t })),
    ...announced.map(e => ({ key: `a-${e.event_id}`, start: startMs(e.start_time), announced: e })),
  ].sort((a, b) => a.start - b.start);
  // A live event IS the current "next event", so the Next Event card only appears when nothing is live.
  const [next, laterUpcoming] = live.length > 0 ? [undefined, upcoming] : [upcoming[0], upcoming.slice(1)];

  const rowFor = (u: Upcoming) =>
    u.tracked
      ? <CalendarRow key={u.key} tournament={u.tracked} onOpen={() => openTournament(toTournament(u.tracked!))} />
      : <AnnouncedRow key={u.key} event={u.announced!} />;

  const empty = !loading && calendar.length === 0 && announced.length === 0;

  // Search: matches name, region or event type across every phase, shown as one flat list (live, then upcoming by date, then completed).
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const matches = (name: string, region: string | null, type: string) =>
    [tournamentDisplayName(name, region), name, region ?? '', TIER_LABELS[type] ?? type].some(s => s.toLowerCase().includes(q));
  const searchResults: React.ReactNode[] = q
    ? [
        ...live.filter(t => matches(t.name, t.region, t.tournament_type)),
        ...upcoming.filter(u => (u.tracked ? matches(u.tracked.name, u.tracked.region, u.tracked.tournament_type) : matches(u.announced!.name, u.announced!.region, u.announced!.tournament_type))),
        ...completed.filter(t => matches(t.name, t.region, t.tournament_type)),
      ].map(item =>
        'key' in item
          ? rowFor(item as Upcoming)
          : <CalendarRow key={(item as CalendarTournamentResponse).id} tournament={item as CalendarTournamentResponse} onOpen={() => openTournament(toTournament(item as CalendarTournamentResponse))} />
      )
    : [];

  return (
    <div className="p-6 page-pad max-w-[900px] mx-auto space-y-4">
      <div>
        <div className="flex items-center gap-1.5">
          <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Tournaments</h1>
          <HelpButton topic="tournaments" size={17} />
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Dividends go to whoever owns a player when the tournament starts. Buying or selling after it starts does not change your payout.
        </p>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 12 }}>
          Updates automatically as tournaments are tracked and results come in. Times are shown in your local time.
        </p>
      </div>

      <input
        type="search"
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Search tournaments by name, region or type"
        aria-label="Search tournaments"
        className="w-full px-4 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
        style={{ background: 'var(--card)', fontSize: 14 }}
      />

      {loading && calendar.length === 0 && (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading calendar…</p>
      )}
      {empty && (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No tournaments announced yet — new ones are picked up automatically.</p>
      )}

      {q ? (
        searchResults.length > 0
          ? <div className="space-y-2.5">{searchResults}</div>
          : <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No tournaments match “{query.trim()}”.</p>
      ) : (<>
      {live.map(t => <LiveEvent key={t.id} tournament={t} onOpen={() => openTournament(toTournament(t))} />)}

      {next && (
        next.tracked ? (
          <FeaturedEvent
            name={next.tracked.name} type={next.tracked.tournament_type} region={next.tracked.region}
            startTime={next.tracked.start_time}
            pool={next.tracked.total_dividend_pool !== null ? toNumber(next.tracked.total_dividend_pool) : null}
            onOpen={() => openTournament(toTournament(next.tracked!))}
          />
        ) : (
          <FeaturedEvent
            name={next.announced!.name} type={next.announced!.tournament_type} region={next.announced!.region}
            startTime={next.announced!.start_time}
            pool={next.announced!.total_dividend_pool !== null ? toNumber(next.announced!.total_dividend_pool) : null}
            note={!next.announced!.finals_confirmed ? 'Announced: the date may change until the Finals are published.' : undefined}
          />
        )
      )}

      {laterUpcoming.length > 0 && (
        <div className="space-y-2.5">
          <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Coming up</p>
          {laterUpcoming.map(rowFor)}
        </div>
      )}

      {completed.length > 0 && (
        <div className="space-y-2.5">
          <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Completed</p>
          {completed.map(t => <CalendarRow key={t.id} tournament={t} onOpen={() => openTournament(toTournament(t))} />)}
        </div>
      )}
      </>)}

      {/* Open qualifier rounds: reference only (no payout), collapsed and off by default, kept apart from the payout events. */}
      <div className="pt-4"><OpenRoundsSection /></div>
    </div>
  );
}
