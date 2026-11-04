import { useState } from 'react';
import { Copy, Mail, MessageSquare, X, Check } from 'lucide-react';
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
          <p style={{ fontSize: 34 }}>💬</p>
          <p className="text-foreground font-semibold mt-2" style={{ fontSize: 16 }}>We'd love to hear your feedback</p>
          <p className="text-muted-foreground mt-2" style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            Ideas, bugs, things that felt confusing, anything you'd change. Email us at
          </p>
          <p className="font-mono font-bold mt-2 break-all" style={{ fontSize: 15, color: 'var(--primary)' }}>{SUPPORT_EMAIL}</p>
          <div className="flex gap-2 mt-5">
            <a
              href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('Forecast feedback')}`}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl font-semibold"
              style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#020610' }}
            >
              <Mail className="w-4 h-4" /> Send an email
            </a>
            <button
              onClick={copy}
              className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl font-semibold hover:bg-white/5"
              style={{ fontSize: 14, color: 'var(--foreground)', border: '1px solid var(--border)' }}
            >
              {copied ? <><Check className="w-4 h-4" /> Copied</> : <><Copy className="w-4 h-4" /> Copy</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
