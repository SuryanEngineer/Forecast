import { useState } from 'react';
import { X } from 'lucide-react';

// Gentle nudge for accounts whose email isn't verified yet. Dismissal lasts for this browser session only.
export function VerifyEmailBanner({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [hidden, setHidden] = useState(() => sessionStorage.getItem('forecast_verify_banner_hidden') === '1');
  if (hidden) return null;
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 border-b" style={{ background: 'rgba(251,191,36,0.08)', borderColor: 'rgba(251,191,36,0.25)' }}>
      <p className="flex-1" style={{ fontSize: 13, color: '#fbbf24' }}>
        Verify your email so you can recover your account if you forget your password.{' '}
        <button onClick={onOpenSettings} className="underline font-semibold">Verify now</button>
      </p>
      <button
        onClick={() => { sessionStorage.setItem('forecast_verify_banner_hidden', '1'); setHidden(true); }}
        className="p-1 rounded hover:bg-white/10" aria-label="Dismiss" style={{ color: '#fbbf24' }}
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
