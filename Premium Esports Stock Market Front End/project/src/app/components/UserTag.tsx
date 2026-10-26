// A player's optional clan-style tag, shown in front of their username: [TAG] name
export function UserTag({ tag, color }: { tag?: string | null; color?: string | null }) {
  if (!tag) return null;
  return (
    <span className="font-mono font-bold mr-1" style={{ color: color || 'var(--primary)', fontSize: '0.92em' }}>
      [{tag}]
    </span>
  );
}

export function NameWithTag({ name, tag, color }: { name: string; tag?: string | null; color?: string | null }) {
  return (
    <>
      <UserTag tag={tag} color={color} />
      {name}
    </>
  );
}
