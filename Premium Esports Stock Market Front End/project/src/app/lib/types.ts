// TypeScript mirrors of forecast-backend's Pydantic response schemas.
// Kept intentionally minimal -- only fields the backend actually returns.
// See forecast-backend/app/schemas/*.py for the source of truth.
//
// Money fields (Decimal on the backend) are typed `Money` (number | string)
// rather than assuming one JSON representation: this codebase was never
// run against a live server while being written (no database available in
// the build environment), and Pydantic's default Decimal-to-JSON encoding
// depends on config that wasn't verified end-to-end. `toNumber()` below
// handles either shape safely -- if you confirm one way or the other once
// this is running against a real backend, this comment (and the union
// type) can be narrowed.
export type Money = number | string;

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  tag?: string | null;
  tag_color?: string | null;
  created_at?: string | null;
}

export interface Profile {
  id: string;
  email: string;
  display_name: string;
  tag: string | null;
  tag_color: string | null;
  tag_colors: string[];
  created_at: string | null;
  name_change_available_at: string | null;
  name_change_cooldown_days: number;
  last_login_at: string | null;
}

export interface SessionRow {
  started_at: string;
  last_seen_at: string;
  active_minutes: number;
  source: string;
  user_agent: string | null;
  ip_address: string | null;
}

export interface SeasonEntryRow {
  position: number;
  user_id: string;
  display_name: string;
  tag: string | null;
  tag_color: string | null;
  start_value: Money;
  current_value: Money;
  return_pct: number;
  season_points: number;
  rank_tier: string;
}

export interface SeasonalLeaderboard {
  season: { id: string; name: string; kind?: string; starts_at: string; ends_at: string | null; ends_tbd?: boolean; finalized?: boolean } | null;
  entries: SeasonEntryRow[];
  me: SeasonEntryRow | null;
  total?: number;
}

export interface SeasonSummary {
  id: string; name: string; kind: string; starts_at: string; ends_at: string | null; ends_tbd: boolean;
  is_active?: boolean; finalized?: boolean;
}

export interface SeasonInfo {
  season: SeasonSummary | null;
  next_season?: SeasonSummary | null;
  ranks: { name: string; min_points: number }[];
  points_per_percent: number;
}

export interface UserStats {
  net_worth: number; cash: number; holdings_value: number; treasury_value: number;
  contributed_capital: number; total_change: number; total_change_pct: number;
  dividend_earnings: number; dividend_payouts: number; interest_earnings: number; fees_paid: number; trading_earnings: number;
  total_trades: number; buy_trades: number; sell_trades: number; trade_volume: number;
  biggest_trade: { player_id: string; gamertag: string; side: string; quantity: number; price: number; value: number; executed_at: string } | null;
  best_day: { day: string; change: number; change_pct: number } | null;
  worst_day: { day: string; change: number; change_pct: number } | null;
  best_holding: { player_id: string; gamertag: string; unrealized: number; pct: number } | null;
  worst_holding: { player_id: string; gamertag: string; unrealized: number; pct: number } | null;
  member_since: string | null; sessions: number; minutes_on_site: number;
  season: (SeasonEntryRow & { rank: string; next_rank: string | null; points_to_next: number; progress: number; season_name: string; ends_at: string | null }) | null;
  season_history: { season_id: string; name: string; final_points: number | null; final_rank: string | null; final_position: number | null; start_value: Money; final_value: Money | null }[];
  history: { day: string; net_worth: number }[];
}

export interface WalletResponse {
  id: string;
  user_id: string;
  cash_balance: Money;
  held_balance: Money;
  available_balance: Money;
}

export interface MarketSnapshot {
  id: string;
  gamertag: string;
  is_verified?: boolean;
  real_name: string | null;
  team: string | null;
  region: string | null;
  total_shares_outstanding: number;
  ipo_price: Money;
  last_price: Money;
  prev_close: Money;
  change: Money;
  change_pct: Money;
  volume_24h: number;
  market_cap: Money;
}

// GET /markets -- paginated. The real roster is tens of thousands of
// players (every entrant Osirion has ever recorded a real result for
// across every tracked tournament, not a small curated list), so this
// always comes back one page at a time -- see the backend's
// app/api/v1/markets.py docstring.
export type MarketSortKey = 'market_cap' | 'price' | 'price_asc' | 'price_desc' | 'volume' | 'hot' | 'gainers' | 'losers';

export interface PaginatedMarketSnapshotResponse {
  items: MarketSnapshot[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// GET /markets/summary -- market-wide totals computed server-side as real
// SQL aggregates over every active player, NOT derived by summing
// whatever single page of markets happens to be loaded (which would only
// reflect that one page once the roster stopped being small).
export interface MarketSummaryResponse {
  total_market_cap: Money;
  total_players: number;
  total_volume_24h: number;
  players_trading: number;
}

export interface PriceHistoryPoint {
  price: Money;
  volume: number;
  recorded_at: string;
}

export interface PositionResponse {
  player_id: string;
  quantity: number;
  held_quantity: number;
  available_quantity: number;
  average_cost: Money;
}

export interface OrderResponse {
  id: string;
  user_id: string;
  player_id: string;
  side: 'buy' | 'sell';
  order_kind: 'limit' | 'quick';
  limit_price: Money | null;
  quantity: number;
  filled_quantity: number;
  status: 'open' | 'partially_filled' | 'filled' | 'cancelled' | 'rejected';
  is_bot: boolean;
  created_at: string;
}

export interface BookLevel {
  price: Money;
  quantity: number;
  orders: number;
}

export interface OrderBookResponse {
  bids: BookLevel[];
  asks: BookLevel[];
  last_trade: Money | null;
}

export interface TradeResponse {
  id: string;
  player_id: string;
  price: Money;
  quantity: number;
  buyer_user_id: string | null;
  seller_user_id: string | null;
  buyer_is_bot: boolean;
  seller_is_bot: boolean;
  executed_at: string;
}

// Server-computed from status/start_time/end_time -- see the backend's
// app/schemas/tournament.py compute_tournament_phase docstring for the
// full reasoning. This, not raw `status`, is what every "is it live /
// upcoming / wrapping up" badge in the UI should read: `status` alone
// stays at 'scheduled'/'results_pending' for a tournament's entire life
// until it finalizes (which can take a while, or historically could get
// stuck), so "not finalized" never meant "happening right now".
export type TournamentPhase = 'upcoming' | 'live' | 'finalizing' | 'completed';

export interface TournamentResponse {
  id: string;
  name: string;
  tournament_type: 'cash_cup' | 'fncs_qualifier' | 'fncs_finals' | 'global_championship' | 'major' | 'other';
  region: string | null;
  start_time: string | null;
  end_time: string | null;
  prize_pool: Money | null;
  status: 'scheduled' | 'results_pending' | 'finalized';
  phase: TournamentPhase;
  created_at: string;
}

// GET /tournaments/calendar -- every tournament that hasn't finalized yet,
// soonest first, with a projected (or, once results start coming in,
// still-projected-until-finalized) total dividend pool. Polled every 45s
// to match the backend's OSIRION_SYNC_INTERVAL_SECONDS, so this updates on
// its own as tournaments get auto-tracked, start, and pay out.
export interface CalendarTournamentResponse {
  id: string;
  name: string;
  tournament_type: 'cash_cup' | 'fncs_qualifier' | 'fncs_finals' | 'global_championship' | 'major' | 'other';
  region: string | null;
  start_time: string | null;
  end_time: string | null;
  status: 'scheduled' | 'results_pending' | 'finalized';
  phase: TournamentPhase;
  total_dividend_pool: Money | null;
  is_osirion_tracked: boolean;
  last_synced_at: string | null;
  entrant_count: number;
}

// GET /tournaments/announced -- future events Osirion has announced that qualify but aren't tracked yet.
export interface AnnouncedTournament {
  event_id: string;
  name: string;
  tournament_type: CalendarTournamentResponse['tournament_type'];
  region: string | null;
  start_time: string | null;
  end_time: string | null;
  total_dividend_pool: Money | null;
  finals_confirmed: boolean;
}

// GET /tournaments/{id}/entrants -- players known to have qualified for a
// tournament before real placement results exist (see the backend's
// TournamentEntrant model). Meaningful only pre-results.
export interface TournamentEntrantResponse {
  player_id: string;
  gamertag: string;
  is_verified?: boolean;
}

export interface LiveLeaderboardEntry {
  player_id: string;
  gamertag: string;
  is_verified?: boolean;
  placement: number;
  points: Money | null;
  eliminations: number | null;
}

// `entries` is just one page -- some real tournaments place thousands of
// competitors (a big-field Cash Cup, not just a small curated lobby), so
// the backend always paginates (default page_size 100) rather than
// shipping everyone at once. See useLiveLeaderboard's page/pageSize args.
export interface LiveLeaderboardResponse {
  tournament_id: string;
  tournament_name: string;
  tournament_status: 'scheduled' | 'results_pending' | 'finalized';
  phase: TournamentPhase;
  is_osirion_tracked: boolean;
  window_begin_time: string | null;
  window_end_time: string | null;
  last_synced_at: string | null;
  total_entries: number;
  page: number;
  page_size: number;
  total_pages: number;
  entries: LiveLeaderboardEntry[];
}

// GET /tournaments/{id}/results -- also paginated, same reasoning as
// LiveLeaderboardResponse above (a finalized tournament can have just as
// many recorded placements as a live one did).
export interface PlacementResultResponse {
  id: string;
  tournament_id: string;
  player_id: string;
  placement: number;
  points: Money | null;
  prize_won: Money | null;
  eliminations: number | null;
  team_id: string | null;
  percentile: Money | null;
  gamertag?: string | null;
  is_verified?: boolean;
}

export interface TeamMemberResponse {
  player_id: string;
  gamertag: string;
  is_verified: boolean;
  pool_amount: Money | null;
  per_share_amount: Money | null;
  is_estimate?: boolean;
  my_shares_at_start: number | null;
  my_payout: Money | null;
}

export interface TeamResultResponse {
  placement: number;
  team_id: string | null;
  points: Money | null;
  eliminations: number | null;
  team_pool_amount: Money | null;
  my_payout: Money | null;
  my_shares_at_start: number | null;
  members: TeamMemberResponse[];
}

export interface PaginatedTeamResultResponse {
  items: TeamResultResponse[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  record_date: string | null;
  my_total_payout: Money | null;
  dividends_paid?: boolean;
}

// GET /tournaments/players/{id}/tournaments -- a player's tournament history for their profile.
export interface PlayerTournamentEntryResponse {
  tournament: TournamentResponse;
  placement: number;
  total_teams: number;
  points: Money | null;
  eliminations: number | null;
  pool_amount: Money | null;
  per_share_amount: Money | null;
  is_estimate: boolean;
}

export interface PlayerTournamentHistoryResponse {
  player_id: string;
  year: number;
  entries: PlayerTournamentEntryResponse[];
  year_total_pool: Money;
  year_per_share: Money;
  year_events: number;
  year_includes_estimates: boolean;
}

export interface GameTeamRowResponse {
  game_placement: number | null;
  eliminations: number | null;
  time_alive: number | null;
  damage_dealt: number | null;
  damage_received: number | null;
  final_placement: number;
  members: TeamMemberResponse[];
}

export interface GameResultsResponse {
  game: number;
  session_id: string | null;
  ended_at: string | null;
  teams: GameTeamRowResponse[];
}

export interface TournamentGamesResponse {
  tournament_id: string;
  games: GameResultsResponse[];
}

export interface GameStatResponse {
  game: number;
  session_id: string | null;
  ended_at: string | null;
  placement: number | null;
  eliminations: number | null;
  points: Money | null;
  stats: Record<string, unknown>;
}

export interface TeamGamesResponse {
  tournament_id: string;
  placement: number;
  members: TeamMemberResponse[];
  games: GameStatResponse[];
  games_played: number;
  wins: number;
  avg_placement: Money | null;
  total_eliminations: number | null;
  total_points: Money | null;
  best_placement: number | null;
}

export interface PaginatedPlacementResultResponse {
  items: PlacementResultResponse[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface LeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  tag?: string | null;
  tag_color?: string | null;
  cash_balance: Money;
  holdings_value: Money;
  portfolio_value: Money;
}

// Portfolio-value-over-time point, for ValueChart.tsx. NOTE: the real
// backend does not currently expose a portfolio value history/snapshot
// endpoint (see forecast-backend/app/api/v1) -- this type exists so
// ValueChart itself can be ported and reused once such an endpoint
// exists, but nothing in this app currently fetches real data into it.
// Do not synthesize fake history client-side; leave callers without a
// real data source omitted instead.
export interface ValueHistoryPoint {
  recorded_at: string;
  value: Money;
}

// Every money field above goes through this instead of a raw parseFloat
// call, so the one place that would need to change (if the backend turns
// out to serialize Decimal as a JSON number vs. a string) is here.
export function toNumber(value: Money | null | undefined): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') return value;
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

// One row of the account activity feed -- GET /wallet/activity (buys, sells, dividends, fees, treasury, deposits).
export interface ActivityItem {
  id: string;
  at: string;
  type: 'buy' | 'sell' | 'dividend' | 'fee' | 'treasury_buy' | 'treasury_redeem' | 'deposit' | 'withdrawal' | string;
  title: string;
  detail: string;
  amount: Money; // signed cash effect: + increases cash, - decreases it
  balance_after: Money;
  player_id: string | null;
  gamertag: string | null;
  quantity: number | null;
  price: Money | null;
}

export interface ActivityPage {
  items: ActivityItem[];
  total: number;
  next_offset: number | null;
}
