import { useEffect, useState } from 'react';

/** Phones and small tablets, in portrait AND landscape. A phone turned sideways is wide (700-950px) but very short, so
 * width alone isn't enough: anything under 900px wide, or under 520px tall (and not a big desktop window), counts. */
const QUERY = '(max-width: 899px), (max-height: 519px) and (max-width: 1199px)';

export function useCompact(): boolean {
  const [compact, setCompact] = useState(() => (typeof window !== 'undefined' ? window.matchMedia(QUERY).matches : false));
  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const on = () => setCompact(mql.matches);
    on();
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, []);
  return compact;
}
