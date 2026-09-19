// Shared "medal" styling for a tournament placement badge -- originally
// lived only inside TournamentDetailModal.tsx; pulled out here so
// LiveLeaderboard.tsx can use the exact same gold/silver/bronze treatment
// instead of a second, slightly-different copy drifting over time.
export function placementBadgeStyle(placement: number): { background: string; color: string } {
  if (placement === 1) return { background: 'rgba(251,191,36,0.2)', color: '#fbbf24' };
  if (placement === 2) return { background: 'rgba(156,163,175,0.15)', color: '#9ca3af' };
  if (placement === 3) return { background: 'rgba(205,127,50,0.15)', color: '#cd7f32' };
  return { background: 'rgba(255,255,255,0.06)', color: 'var(--muted-foreground)' };
}

// A subtle full-row tint for the top 3 -- used by LiveLeaderboard so a
// podium finish reads at a glance even scrolling past quickly, without
// being as loud as the badge color itself.
export function placementRowTint(placement: number): string {
  if (placement === 1) return 'rgba(251,191,36,0.06)';
  if (placement === 2) return 'rgba(156,163,175,0.05)';
  if (placement === 3) return 'rgba(205,127,50,0.05)';
  return 'rgba(255,255,255,0.03)';
}

