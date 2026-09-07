export type Region = 'NAE' | 'NAW' | 'EU' | 'OCE' | 'BR' | 'ME';
export type FormResult = 'W' | 'L' | 'T';
export type TournamentStatus = 'upcoming' | 'live' | 'completed';

export interface Player {
  id: string;
  name: string;
  realName: string;
  team: string;
  teamColor: string;
  region: Region;
  nationality: string;
  age: number;
  price: number;
  prevClose: number;
  change: number;
  changePercent: number;
  high52: number;
  low52: number;
  marketCap: number;
  volume: number;
  avgVolume: number;
  dividendYield: number;
  dividendPerShare: number;
  totalPR: number;
  tournamentWins: number;
  top5s: number;
  top10s: number;
  consistency: number;
  elo: number;
  recentForm: FormResult[];
  priceHistory90: number[];
  priceHistory30: number[];
  description: string;
}

export interface PortfolioHolding {
  playerId: string;
  shares: number;
  avgCost: number;
  allocationPercent: number;
}

export interface Tournament {
  id: string;
  name: string;
  type: 'Solo' | 'Duo' | 'Squad';
  format: string;
  date: string;
  prizePool: number;
  regions: Region[];
  status: TournamentStatus;
  location: string;
  top5?: Array<{ playerId: string; placement: number; earnings: number; points: number }>;
  dividendMultiplier?: number;
}

export interface LeaderboardEntry {
  rank: number;
  userId: string;
  username: string;
  initials: string;
  color: string;
  portfolioValue: number;
  elo: number;
  weeklyReturn: number;
  monthlyReturn: number;
  topHolding: string;
  isCurrentUser?: boolean;
}

export interface DividendEvent {
  date: string;
  playerId: string;
  amount: number;
  shares: number;
  tournament: string;
  placement: number;
}

function seededRng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) | 0;
    return Math.abs(s) / 2147483648;
  };
}

function generatePriceHistory(endPrice: number, days: number, seed: number, volatility = 0.022): number[] {
  const rng = seededRng(seed);
  const prices: number[] = [endPrice];
  for (let i = 1; i < days; i++) {
    const prev = prices[0];
    const trend = rng() > 0.48 ? 0.001 : -0.001;
    const noise = (rng() - 0.5) * volatility;
    prices.unshift(Math.max(prev * (1 + trend + noise), 5));
  }
  return prices.map(p => Math.round(p * 100) / 100);
}

export const PLAYERS: Player[] = [
  {
    id: 'bugha',
    name: 'Bugha',
    realName: 'Kyle Giersdorf',
    team: 'FaZe Clan',
    teamColor: '#FF4655',
    region: 'NAE',
    nationality: 'US',
    age: 21,
    price: 284.50,
    prevClose: 275.60,
    change: 8.90,
    changePercent: 3.23,
    high52: 318.40,
    low52: 194.70,
    marketCap: 28450000,
    volume: 184200,
    avgVolume: 156800,
    dividendYield: 2.1,
    dividendPerShare: 5.97,
    totalPR: 3847200,
    tournamentWins: 12,
    top5s: 28,
    top10s: 41,
    consistency: 87,
    elo: 3247,
    recentForm: ['W', 'W', 'T', 'L', 'W'],
    priceHistory90: generatePriceHistory(284.50, 90, 42),
    priceHistory30: generatePriceHistory(284.50, 30, 43),
    description: 'World Cup Solo champion and consistent NAE top performer. Known for aggressive rotations and elite endgame IQ.',
  },
  {
    id: 'clix',
    name: 'Clix',
    realName: 'Cody Conrod',
    team: 'NRG',
    teamColor: '#F6861F',
    region: 'NAE',
    nationality: 'US',
    age: 19,
    price: 198.20,
    prevClose: 201.10,
    change: -2.90,
    changePercent: -1.44,
    high52: 247.60,
    low52: 156.30,
    marketCap: 19820000,
    volume: 142700,
    avgVolume: 138400,
    dividendYield: 1.8,
    dividendPerShare: 3.57,
    totalPR: 1824600,
    tournamentWins: 6,
    top5s: 19,
    top10s: 32,
    consistency: 78,
    elo: 2941,
    recentForm: ['L', 'W', 'T', 'W', 'L'],
    priceHistory90: generatePriceHistory(198.20, 90, 77),
    priceHistory30: generatePriceHistory(198.20, 30, 78),
    description: 'High-octane box fighter and content creator turned full-time competitor. Explosive mechanical skill with high variance.',
  },
  {
    id: 'benjyfishy',
    name: 'benjyfishy',
    realName: 'Benjamin Fish',
    team: 'Alliance',
    teamColor: '#0071CE',
    region: 'EU',
    nationality: 'GB',
    age: 20,
    price: 176.40,
    prevClose: 171.60,
    change: 4.80,
    changePercent: 2.80,
    high52: 212.30,
    low52: 142.80,
    marketCap: 17640000,
    volume: 98400,
    avgVolume: 92100,
    dividendYield: 1.9,
    dividendPerShare: 3.35,
    totalPR: 1642400,
    tournamentWins: 8,
    top5s: 22,
    top10s: 37,
    consistency: 82,
    elo: 3012,
    recentForm: ['W', 'T', 'W', 'W', 'L'],
    priceHistory90: generatePriceHistory(176.40, 90, 104),
    priceHistory30: generatePriceHistory(176.40, 30, 105),
    description: 'Tactical EU stalwart with exceptional consistency. Former World Cup finalist with refined zone exploitation mechanics.',
  },
  {
    id: 'mrsavage',
    name: 'MrSavage',
    realName: 'Martin Foss Andersen',
    team: 'NRG',
    teamColor: '#F6861F',
    region: 'EU',
    nationality: 'NO',
    age: 20,
    price: 221.80,
    prevClose: 219.80,
    change: 2.00,
    changePercent: 0.91,
    high52: 268.90,
    low52: 176.40,
    marketCap: 22180000,
    volume: 118300,
    avgVolume: 124600,
    dividendYield: 2.3,
    dividendPerShare: 5.10,
    totalPR: 2318700,
    tournamentWins: 9,
    top5s: 24,
    top10s: 38,
    consistency: 84,
    elo: 3108,
    recentForm: ['W', 'L', 'W', 'T', 'W'],
    priceHistory90: generatePriceHistory(221.80, 90, 131),
    priceHistory30: generatePriceHistory(221.80, 30, 132),
    description: 'Norwegian prodigy and EU elite. Exceptional duo synergy and reads opponent behavior with surgical precision.',
  },
  {
    id: 'mitr0',
    name: 'mitr0',
    realName: 'Emad Nasif',
    team: 'FaZe Clan',
    teamColor: '#FF4655',
    region: 'EU',
    nationality: 'DK',
    age: 21,
    price: 167.30,
    prevClose: 171.00,
    change: -3.70,
    changePercent: -2.16,
    high52: 224.10,
    low52: 134.60,
    marketCap: 16730000,
    volume: 87200,
    avgVolume: 91400,
    dividendYield: 1.6,
    dividendPerShare: 2.68,
    totalPR: 1437200,
    tournamentWins: 7,
    top5s: 18,
    top10s: 31,
    consistency: 76,
    elo: 2876,
    recentForm: ['T', 'L', 'W', 'L', 'T'],
    priceHistory90: generatePriceHistory(167.30, 90, 163),
    priceHistory30: generatePriceHistory(167.30, 30, 164),
    description: 'Aggressive fragger with elite mechanical aim. High-ceiling but streaky — known for either winning or placing top 5.',
  },
  {
    id: 'epikwhale',
    name: 'EpikWhale',
    realName: 'Shane Cotton',
    team: 'Cloud9',
    teamColor: '#00BFFF',
    region: 'NAW',
    nationality: 'US',
    age: 20,
    price: 143.60,
    prevClose: 137.90,
    change: 5.70,
    changePercent: 4.13,
    high52: 178.40,
    low52: 98.30,
    marketCap: 14360000,
    volume: 76800,
    avgVolume: 68200,
    dividendYield: 1.4,
    dividendPerShare: 2.01,
    totalPR: 987400,
    tournamentWins: 4,
    top5s: 14,
    top10s: 24,
    consistency: 71,
    elo: 2724,
    recentForm: ['W', 'W', 'T', 'L', 'W'],
    priceHistory90: generatePriceHistory(143.60, 90, 197),
    priceHistory30: generatePriceHistory(143.60, 30, 198),
    description: 'NAW region king with dominant local tournament presence. Unorthodox builds and creative mid-game pressure.',
  },
  {
    id: 'aqua',
    name: 'Aqua',
    realName: 'David Wang',
    team: 'Wave',
    teamColor: '#00D4AA',
    region: 'EU',
    nationality: 'AT',
    age: 22,
    price: 134.90,
    prevClose: 133.30,
    change: 1.60,
    changePercent: 1.20,
    high52: 189.20,
    low52: 104.70,
    marketCap: 13490000,
    volume: 64300,
    avgVolume: 71800,
    dividendYield: 1.7,
    dividendPerShare: 2.29,
    totalPR: 1284600,
    tournamentWins: 5,
    top5s: 16,
    top10s: 28,
    consistency: 74,
    elo: 2798,
    recentForm: ['L', 'W', 'W', 'T', 'L'],
    priceHistory90: generatePriceHistory(134.90, 90, 228),
    priceHistory30: generatePriceHistory(134.90, 30, 229),
    description: 'World Cup Duo champion and respected EU veteran. Champion-level positioning and calculated risk management.',
  },
  {
    id: 'queasy',
    name: 'queasy',
    realName: 'Mikhail Ayzenberg',
    team: 'Guild Esports',
    teamColor: '#9B59B6',
    region: 'EU',
    nationality: 'UA',
    age: 20,
    price: 156.20,
    prevClose: 155.70,
    change: 0.50,
    changePercent: 0.32,
    high52: 198.60,
    low52: 118.40,
    marketCap: 15620000,
    volume: 54700,
    avgVolume: 58900,
    dividendYield: 1.5,
    dividendPerShare: 2.34,
    totalPR: 1124800,
    tournamentWins: 6,
    top5s: 17,
    top10s: 30,
    consistency: 80,
    elo: 2967,
    recentForm: ['W', 'T', 'W', 'W', 'T'],
    priceHistory90: generatePriceHistory(156.20, 90, 254),
    priceHistory30: generatePriceHistory(156.20, 30, 255),
    description: 'Strategic FNCS specialist with exceptional consistency. Reads meta adaptations faster than almost any peer in EU.',
  },
  {
    id: 'acorn',
    name: 'acorn',
    realName: 'Kyle Rose',
    team: 'FaZe Clan',
    teamColor: '#FF4655',
    region: 'NAE',
    nationality: 'US',
    age: 18,
    price: 98.70,
    prevClose: 93.30,
    change: 5.40,
    changePercent: 5.79,
    high52: 132.40,
    low52: 62.10,
    marketCap: 9870000,
    volume: 112400,
    avgVolume: 67300,
    dividendYield: 0.9,
    dividendPerShare: 0.89,
    totalPR: 642400,
    tournamentWins: 2,
    top5s: 9,
    top10s: 17,
    consistency: 69,
    elo: 2587,
    recentForm: ['W', 'L', 'W', 'T', 'W'],
    priceHistory90: generatePriceHistory(98.70, 90, 279),
    priceHistory30: generatePriceHistory(98.70, 30, 280),
    description: 'Breakout talent at just 18. Recent FNCS victory sparked a surge of investor interest. Volatility is high but ceiling is elite.',
  },
  {
    id: 'mongraal',
    name: 'Mongraal',
    realName: 'Kyle Jackson',
    team: 'FaZe Clan',
    teamColor: '#FF4655',
    region: 'EU',
    nationality: 'GB',
    age: 19,
    price: 189.40,
    prevClose: 184.20,
    change: 5.20,
    changePercent: 2.82,
    high52: 234.80,
    low52: 152.60,
    marketCap: 18940000,
    volume: 134600,
    avgVolume: 118700,
    dividendYield: 1.7,
    dividendPerShare: 3.22,
    totalPR: 1742300,
    tournamentWins: 7,
    top5s: 21,
    top10s: 35,
    consistency: 79,
    elo: 2994,
    recentForm: ['T', 'W', 'W', 'L', 'W'],
    priceHistory90: generatePriceHistory(189.40, 90, 301),
    priceHistory30: generatePriceHistory(189.40, 30, 302),
    description: 'Prodigy who turned pro at 13. Exceptional builder with the fastest edit speed in EU. Content appeal adds off-season value.',
  },
  {
    id: 'tayson',
    name: 'Tayson',
    realName: 'Thijs Molendijk',
    team: 'Team Liquid',
    teamColor: '#1CA9C9',
    region: 'EU',
    nationality: 'NL',
    age: 21,
    price: 127.60,
    prevClose: 131.40,
    change: -3.80,
    changePercent: -2.89,
    high52: 172.30,
    low52: 94.80,
    marketCap: 12760000,
    volume: 67800,
    avgVolume: 74200,
    dividendYield: 1.3,
    dividendPerShare: 1.66,
    totalPR: 987200,
    tournamentWins: 4,
    top5s: 13,
    top10s: 24,
    consistency: 71,
    elo: 2713,
    recentForm: ['L', 'L', 'T', 'W', 'L'],
    priceHistory90: generatePriceHistory(127.60, 90, 331),
    priceHistory30: generatePriceHistory(127.60, 30, 332),
    description: 'Dutch talent known for unorthodox strategies and psychological warfare. Form dips cost investor confidence this season.',
  },
  {
    id: 'veno',
    name: 'Veno',
    realName: 'Victor Lopes',
    team: 'TSM',
    teamColor: '#888888',
    region: 'NAE',
    nationality: 'US',
    age: 18,
    price: 89.30,
    prevClose: 90.10,
    change: -0.80,
    changePercent: -0.89,
    high52: 118.70,
    low52: 58.40,
    marketCap: 8930000,
    volume: 38400,
    avgVolume: 44100,
    dividendYield: 0.7,
    dividendPerShare: 0.63,
    totalPR: 387200,
    tournamentWins: 2,
    top5s: 8,
    top10s: 15,
    consistency: 62,
    elo: 2441,
    recentForm: ['T', 'L', 'L', 'W', 'T'],
    priceHistory90: generatePriceHistory(89.30, 90, 357),
    priceHistory30: generatePriceHistory(89.30, 30, 358),
    description: 'Emerging NAE talent with strong mechanical fundamentals. Inconsistency in high-stakes play makes this a high-risk hold.',
  },
];

export const PORTFOLIO_HOLDINGS: PortfolioHolding[] = [
  { playerId: 'bugha', shares: 12, avgCost: 241.30, allocationPercent: 34.2 },
  { playerId: 'mrsavage', shares: 15, avgCost: 198.40, allocationPercent: 28.3 },
  { playerId: 'queasy', shares: 18, avgCost: 138.70, allocationPercent: 21.3 },
  { playerId: 'acorn', shares: 22, avgCost: 76.40, allocationPercent: 11.0 },
  { playerId: 'epikwhale', shares: 7, avgCost: 129.80, allocationPercent: 5.2 },
];

export const TOURNAMENTS: Tournament[] = [
  {
    id: 'fncs-ch3-s4-grand-finals',
    name: 'FNCS Chapter 3 Season 4 Grand Finals',
    type: 'Solo',
    format: 'Six games, best aggregate score',
    date: '2026-08-15',
    prizePool: 2000000,
    regions: ['NAE', 'EU', 'NAW', 'OCE', 'BR'],
    status: 'upcoming',
    location: 'Online (All Regions)',
    dividendMultiplier: 2.0,
  },
  {
    id: 'dreamhack-open-2026',
    name: 'DreamHack Open 2026',
    type: 'Duo',
    format: 'Eight games, point accumulation',
    date: '2026-08-03',
    prizePool: 500000,
    regions: ['NAE', 'EU'],
    status: 'upcoming',
    location: 'Stockholm, Sweden',
    dividendMultiplier: 1.5,
  },
  {
    id: 'cash-cup-naeast-w3',
    name: 'Cash Cup NAE Week 3',
    type: 'Solo',
    format: 'Ten games, limited format',
    date: '2026-07-28',
    prizePool: 50000,
    regions: ['NAE'],
    status: 'upcoming',
    location: 'Online (NAE)',
    dividendMultiplier: 1.2,
  },
  {
    id: 'fncs-ch3-s3-grand-finals',
    name: 'FNCS Chapter 3 Season 3 Grand Finals',
    type: 'Solo',
    format: 'Six games, best aggregate score',
    date: '2026-06-14',
    prizePool: 2000000,
    regions: ['NAE', 'EU', 'NAW', 'OCE', 'BR'],
    status: 'completed',
    location: 'Online (All Regions)',
    dividendMultiplier: 2.0,
    top5: [
      { playerId: 'bugha', placement: 1, earnings: 300000, points: 142 },
      { playerId: 'mrsavage', placement: 2, earnings: 175000, points: 138 },
      { playerId: 'benjyfishy', placement: 3, earnings: 125000, points: 131 },
      { playerId: 'queasy', placement: 4, earnings: 100000, points: 128 },
      { playerId: 'mongraal', placement: 5, earnings: 75000, points: 124 },
    ],
  },
  {
    id: 'dreamhack-fall-2026',
    name: 'DreamHack Fall 2025',
    type: 'Duo',
    format: 'Eight games, point accumulation',
    date: '2026-05-20',
    prizePool: 500000,
    regions: ['NAE', 'EU'],
    status: 'completed',
    location: 'Dallas, TX',
    dividendMultiplier: 1.5,
    top5: [
      { playerId: 'aqua', placement: 1, earnings: 80000, points: 118 },
      { playerId: 'mitr0', placement: 2, earnings: 50000, points: 112 },
      { playerId: 'clix', placement: 3, earnings: 35000, points: 108 },
      { playerId: 'epikwhale', placement: 4, earnings: 25000, points: 104 },
      { playerId: 'bugha', placement: 5, earnings: 18000, points: 101 },
    ],
  },
  {
    id: 'cash-cup-eu-w1',
    name: 'Cash Cup EU Week 1',
    type: 'Solo',
    format: 'Ten games, limited format',
    date: '2026-07-07',
    prizePool: 50000,
    regions: ['EU'],
    status: 'completed',
    location: 'Online (EU)',
    dividendMultiplier: 1.2,
    top5: [
      { playerId: 'queasy', placement: 1, earnings: 8000, points: 89 },
      { playerId: 'benjyfishy', placement: 2, earnings: 5500, points: 84 },
      { playerId: 'tayson', placement: 3, earnings: 4000, points: 82 },
      { playerId: 'mrsavage', placement: 4, earnings: 3200, points: 79 },
      { playerId: 'aqua', placement: 5, earnings: 2500, points: 77 },
    ],
  },
];

export const LEADERBOARD: LeaderboardEntry[] = [
  { rank: 1, userId: 'u1', username: 'Vaultbreaker', initials: 'VB', color: '#00c8ff', portfolioValue: 182400, elo: 3892, weeklyReturn: 4.7, monthlyReturn: 18.2, topHolding: 'Bugha' },
  { rank: 2, userId: 'u2', username: 'EliteHedge', initials: 'EH', color: '#10d9a0', portfolioValue: 174200, elo: 3741, weeklyReturn: 2.1, monthlyReturn: 14.8, topHolding: 'MrSavage' },
  { rank: 3, userId: 'u3', username: 'AlphaFnatics', initials: 'AF', color: '#9b6fff', portfolioValue: 168900, elo: 3618, weeklyReturn: 6.3, monthlyReturn: 22.1, topHolding: 'Mongraal' },
  { rank: 4, userId: 'u4', username: 'StormPicker', initials: 'SP', color: '#ff8c42', portfolioValue: 156700, elo: 3502, weeklyReturn: -1.2, monthlyReturn: 11.4, topHolding: 'Bugha' },
  { rank: 5, userId: 'u5', username: 'GGInvestor', initials: 'GG', color: '#ff3d5c', portfolioValue: 147300, elo: 3387, weeklyReturn: 3.8, monthlyReturn: 9.7, topHolding: 'queasy' },
  { rank: 6, userId: 'u6', username: 'ProCircuit', initials: 'PC', color: '#fbbf24', portfolioValue: 138100, elo: 3264, weeklyReturn: 1.4, monthlyReturn: 7.2, topHolding: 'benjyfishy' },
  { rank: 7, userId: 'u7', username: 'Dividends', initials: 'DV', color: '#00c8ff', portfolioValue: 129600, elo: 3148, weeklyReturn: 5.2, monthlyReturn: 16.4, topHolding: 'acorn' },
  { rank: 8, userId: 'u8', username: 'LongGameKing', initials: 'LG', color: '#10d9a0', portfolioValue: 117400, elo: 3021, weeklyReturn: -0.8, monthlyReturn: 5.9, topHolding: 'MrSavage' },
  { rank: 9, userId: 'u9', username: 'MetaTrader99', initials: 'MT', color: '#9b6fff', portfolioValue: 108200, elo: 2944, weeklyReturn: 2.9, monthlyReturn: 8.3, topHolding: 'EpikWhale' },
  { rank: 10, userId: 'u10', username: 'ZoneControl', initials: 'ZC', color: '#ff8c42', portfolioValue: 97800, elo: 2871, weeklyReturn: -3.1, monthlyReturn: 3.4, topHolding: 'Clix' },
  { rank: 11, userId: 'u11', username: 'ElimPoints', initials: 'EP', color: '#00c8ff', portfolioValue: 89300, elo: 2792, weeklyReturn: 1.6, monthlyReturn: 6.8, topHolding: 'Aqua' },
  { rank: 12, userId: 'u12', username: 'BattlePass', initials: 'BP', color: '#10d9a0', portfolioValue: 83600, elo: 2714, weeklyReturn: 4.1, monthlyReturn: 12.7, topHolding: 'benjyfishy' },
  { rank: 13, userId: 'u13', username: 'DropFirst', initials: 'DF', color: '#9b6fff', portfolioValue: 77200, elo: 2638, weeklyReturn: -1.7, monthlyReturn: 2.1, topHolding: 'mitr0' },
  { rank: 14, userId: 'u14', username: 'RngKills', initials: 'RK', color: '#ff3d5c', portfolioValue: 71400, elo: 2561, weeklyReturn: 7.4, monthlyReturn: 19.8, topHolding: 'acorn' },
  { rank: 15, userId: 'u15', username: 'FncsWatcher', initials: 'FW', color: '#fbbf24', portfolioValue: 65800, elo: 2487, weeklyReturn: 0.3, monthlyReturn: 4.6, topHolding: 'Mongraal' },
  { rank: 142, userId: 'current', username: 'You', initials: 'KM', color: '#00c8ff', portfolioValue: 47284, elo: 2847, weeklyReturn: 2.71, monthlyReturn: 9.4, topHolding: 'Bugha', isCurrentUser: true },
];

export const DIVIDEND_HISTORY: DividendEvent[] = [
  { date: '2026-06-14', playerId: 'bugha', amount: 71.64, shares: 12, tournament: 'FNCS Ch3 S3 Grand Finals', placement: 1 },
  { date: '2026-06-14', playerId: 'mrsavage', amount: 76.50, shares: 15, tournament: 'FNCS Ch3 S3 Grand Finals', placement: 2 },
  { date: '2026-06-14', playerId: 'queasy', amount: 42.12, shares: 18, tournament: 'FNCS Ch3 S3 Grand Finals', placement: 4 },
  { date: '2026-07-07', playerId: 'queasy', amount: 28.08, shares: 18, tournament: 'Cash Cup EU Week 1', placement: 1 },
  { date: '2026-07-07', playerId: 'mrsavage', amount: 19.95, shares: 15, tournament: 'Cash Cup EU Week 1', placement: 4 },
  { date: '2026-05-20', playerId: 'acorn', amount: 12.32, shares: 22, tournament: 'DreamHack Fall 2025', placement: 8 },
  { date: '2026-05-20', playerId: 'epikwhale', amount: 13.65, shares: 7, tournament: 'DreamHack Fall 2025', placement: 4 },
  { date: '2026-04-12', playerId: 'bugha', amount: 52.74, shares: 12, tournament: 'FNCS Ch3 S2 Grand Finals', placement: 2 },
];

export const MARKET_NEWS = [
  {
    id: 'n1',
    date: '2026-07-24',
    title: 'acorn wins Cash Cup NAE — price surges 5.8%',
    body: 'FaZe Clan\'s youngest roster member dominated a stacked field of 500+ competitors, earning his second title this season.',
    impact: 'positive',
    playerId: 'acorn',
    priceImpact: +5.79,
  },
  {
    id: 'n2',
    date: '2026-07-23',
    title: 'EpikWhale qualifies for FNCS Grand Finals',
    body: 'Cloud9\'s NAW representative secured his spot in the season-ending Grand Finals with a dominant qualifier run.',
    impact: 'positive',
    playerId: 'epikwhale',
    priceImpact: +4.13,
  },
  {
    id: 'n3',
    date: '2026-07-22',
    title: 'Clix drops out of DreamHack amid scheduling conflict',
    body: 'NRG confirmed that Clix will not compete at DreamHack Open 2026 in Stockholm due to personal scheduling constraints.',
    impact: 'negative',
    playerId: 'clix',
    priceImpact: -2.4,
  },
  {
    id: 'n4',
    date: '2026-07-21',
    title: 'Tayson posts underwhelming Cash Cup results',
    body: 'The Dutch star placed 47th in EU Cash Cup, missing point threshold for dividends for the third consecutive week.',
    impact: 'negative',
    playerId: 'tayson',
    priceImpact: -2.89,
  },
  {
    id: 'n5',
    date: '2026-07-20',
    title: 'Bugha and MrSavage announce DreamHack duo partnership',
    body: 'Two of the world\'s top-ranked players confirmed a surprise duo entry for DreamHack Open 2026, driving both stocks higher.',
    impact: 'positive',
    playerId: 'bugha',
    priceImpact: +1.8,
  },
];

export interface PendingOrder {
  id: string;
  type: 'buy' | 'sell';
  playerId: string;
  playerName: string;
  shares: number;
  targetPrice: number;
  createdAt: string;
}

export const INVESTOR_PORTFOLIOS: Record<string, Array<{ playerId: string; shares: number; avgCost: number }>> = {
  u1: [
    { playerId: 'bugha', shares: 48, avgCost: 210.20 },
    { playerId: 'mrsavage', shares: 35, avgCost: 185.40 },
    { playerId: 'mitr0', shares: 22, avgCost: 145.80 },
    { playerId: 'benjyfishy', shares: 18, avgCost: 152.30 },
  ],
  u2: [
    { playerId: 'mrsavage', shares: 55, avgCost: 178.90 },
    { playerId: 'queasy', shares: 40, avgCost: 122.60 },
    { playerId: 'aqua', shares: 30, avgCost: 118.40 },
  ],
  u3: [
    { playerId: 'mongraal', shares: 60, avgCost: 155.20 },
    { playerId: 'benjyfishy', shares: 44, avgCost: 138.70 },
    { playerId: 'clix', shares: 25, avgCost: 174.80 },
    { playerId: 'epikwhale', shares: 20, avgCost: 112.30 },
  ],
  u4: [
    { playerId: 'bugha', shares: 38, avgCost: 241.50 },
    { playerId: 'acorn', shares: 70, avgCost: 68.20 },
    { playerId: 'veno', shares: 55, avgCost: 74.10 },
  ],
  u5: [
    { playerId: 'queasy', shares: 52, avgCost: 130.40 },
    { playerId: 'tayson', shares: 44, avgCost: 118.60 },
    { playerId: 'mitr0', shares: 30, avgCost: 152.30 },
  ],
  current: [
    { playerId: 'bugha', shares: 12, avgCost: 241.30 },
    { playerId: 'mrsavage', shares: 15, avgCost: 198.40 },
    { playerId: 'queasy', shares: 18, avgCost: 138.70 },
    { playerId: 'acorn', shares: 22, avgCost: 76.40 },
    { playerId: 'epikwhale', shares: 7, avgCost: 129.80 },
  ],
};

export function getPlayer(id: string): Player | undefined {
  return PLAYERS.find(p => p.id === id);
}

export function formatCurrency(n: number, decimals = 2): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function formatCompact(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n}`;
}

export const PORTFOLIO_PERFORMANCE_30D = (() => {
  const rng = seededRng(9999);
  const data = [];
  let value = 42000;
  for (let i = 29; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const change = (rng() - 0.46) * 0.018;
    value = value * (1 + change);
    data.push({
      date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      value: Math.round(value),
      market: Math.round(value * (0.94 + rng() * 0.04)),
    });
  }
  // Force last value
  data[data.length - 1].value = 47284;
  return data;
})();
