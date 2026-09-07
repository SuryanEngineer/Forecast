// A small "ⓘ" info-circle button for defining a single metric inline --
// deliberately lighter-weight than HelpModal.tsx's HelpButton (which
// opens a full deep-dive modal about a whole topic like "How Dividends
// Work"). This is for "what does THIS specific number mean" -- a couple
// sentences in a small popover, not a multi-section explainer. Uses a
// different icon (a literal "i" in a circle, via lucide's Info) than
// HelpButton's "?" (HelpCircle) on purpose, so the two affordances read
// as visually distinct once someone learns what each one does.
import { useState } from 'react';
import { Info } from 'lucide-react';

interface Props {
  text: string;
  size?: number;
  // Which edge of the icon the popover's own edge aligns to, so it opens
  // toward the middle of the screen instead of running off it. Use
  // "right" for icons near the right edge of their container.
  align?: 'left' | 'right';
}

export function InfoDot({ text, size = 13, align = 'left' }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex" onClick={e => e.stopPropagation()}>
      <button
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center justify-center rounded-full transition-colors"
        style={{ width: size + 6, height: size + 6, color: open ? 'var(--primary)' : 'var(--muted-foreground)' }}
        aria-label="More info"
      >
        <Info style={{ width: size, height: size }} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute z-50 top-full mt-1.5 rounded-xl border border-border p-3"
            style={{
              background: 'var(--popover)',
              width: 220,
              [align]: 0,
              fontSize: 12,
              lineHeight: 1.55,
              color: 'var(--foreground)',
              boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
            }}
          >
            {text}
          </div>
        </>
      )}
    </span>
  );
}
