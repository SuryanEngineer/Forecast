import { useEffect, useState } from 'react';
import { subscribeWaking } from '../lib/api';

/** A small notice at the top of the page while the (free-tier) server is waking up from sleep, which can take up to a
 * minute. It disappears on its own the moment the server answers. */
export function ServerWakingBanner() {
  const [waking, setWaking] = useState(false);
  useEffect(() => subscribeWaking(setWaking), []);
  if (!waking) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed left-1/2 -translate-x-1/2 px-4 py-2 rounded-full border border-border text-foreground flex items-center gap-2"
      style={{ top: 'max(12px, env(safe-area-inset-top))', zIndex: 60, background: 'var(--card)', fontSize: 13, boxShadow: '0 4px 20px rgba(0,0,0,0.35)', maxWidth: 'calc(100vw - 24px)' }}
    >
      <span className="inline-block rounded-full animate-pulse" style={{ width: 8, height: 8, background: 'var(--primary)' }} />
      <span>Waking the server up. This can take up to a minute after it has been idle.</span>
    </div>
  );
}
