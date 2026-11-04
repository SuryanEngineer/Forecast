import { useState } from 'react';
import { Copy, MessageSquare, X, Check } from 'lucide-react';
import { SUPPORT_EMAIL } from './LegalModal';

export function FeedbackModal({ onClose }: { onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(SUPPORT_EMAIL);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard can be blocked; the address is shown on screen anyway */
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 modal-overlay" style={{ background: 'rgba(2,6,16,0.78)' }} onClick={onClose}>
      <div
        className="w-full max-w-[440px] rounded-2xl border border-border modal-panel"
        style={{ background: 'var(--card)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5" style={{ color: 'var(--primary)' }} />
            <p className="font-bold" style={{ fontSize: 17, color: 'var(--foreground)' }}>Feedback</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-4 sm:px-6 py-6 text-center">
          <div className="mx-auto w-14 h-14 rounded-full flex items-center justify-center" style={{ background: 'rgba(0,200,255,0.12)' }}>
            <MessageSquare className="w-7 h-7" style={{ color: 'var(--primary)' }} />
          </div>
          <p className="text-foreground font-semibold mt-2" style={{ fontSize: 16 }}>We'd love to hear your feedback</p>
          <p className="text-muted-foreground mt-2" style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            Ideas, bugs, things that felt confusing, anything you'd change. Email us at
          </p>
          <div className="flex items-center justify-center gap-2 mt-2">
            <p className="font-mono font-bold break-all" style={{ fontSize: 15, color: 'var(--primary)' }}>{SUPPORT_EMAIL}</p>
            <button
              onClick={copy}
              className="p-1.5 rounded-lg hover:bg-white/10 shrink-0"
              style={{ color: copied ? 'var(--gain)' : 'var(--muted-foreground)' }}
              aria-label={copied ? 'Copied' : 'Copy email address'}
              title={copied ? 'Copied' : 'Copy'}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
