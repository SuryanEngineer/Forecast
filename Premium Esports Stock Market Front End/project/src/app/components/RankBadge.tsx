// Ranked-ladder badge (Bronze / Gold / Diamond I-III, Unreal).
const TIER_STYLE: Record<string, { color: string; glow: string; icon: string }> = {
  Bronze: { color: '#cd7f32', glow: 'rgba(205,127,50,0.18)', icon: '◆' },
  Gold: { color: '#fbbf24', glow: 'rgba(251,191,36,0.18)', icon: '◆' },
  Diamond: { color: '#67e8f9', glow: 'rgba(103,232,249,0.2)', icon: '◆' },
  Unreal: { color: '#c084fc', glow: 'rgba(192,132,252,0.25)', icon: '★' },
};

export function tierOf(rank: string): string {
  return rank.split(' ')[0];
}

export function rankColor(rank: string): string {
  return (TIER_STYLE[tierOf(rank)] ?? TIER_STYLE.Bronze).color;
}

export function RankBadge({ rank, size = 'md' }: { rank: string; size?: 'sm' | 'md' | 'lg' }) {
  const t = TIER_STYLE[tierOf(rank)] ?? TIER_STYLE.Bronze;
  const fs = size === 'lg' ? 15 : size === 'sm' ? 10 : 12;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full font-bold whitespace-nowrap"
      style={{
        fontSize: fs,
        padding: size === 'lg' ? '5px 12px' : '2px 8px',
        color: t.color,
        background: t.glow,
        border: `1px solid ${t.color}55`,
      }}
    >
      <span style={{ fontSize: fs - 1 }}>{t.icon}</span>
      {rank}
    </span>
  );
}
