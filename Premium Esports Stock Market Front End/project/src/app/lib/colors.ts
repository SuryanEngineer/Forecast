// The backend doesn't store a "team color" for players (that was Figma
// mock flavor, not part of the economic model) -- this derives a stable
// color per id instead, so avatars/badges still look varied without
// inventing backend schema for pure cosmetics.
const PALETTE = ['#00c8ff', '#10d9a0', '#9b6fff', '#ff8c42', '#fbbf24', '#ff3d5c', '#1CA9C9', '#F6861F'];

export function colorForId(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}
