import { Loader2 } from 'lucide-react';

/** A small spinning indicator for a value that is still being worked out. */
export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-muted-foreground" role="status" aria-live="polite">
      <Loader2 className="animate-spin" style={{ width: size, height: size, color: 'var(--primary)' }} />
      {label && <span style={{ fontSize: Math.max(11, size * 0.7) }}>{label}</span>}
    </span>
  );
}
