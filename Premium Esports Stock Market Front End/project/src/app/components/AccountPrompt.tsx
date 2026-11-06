import { Lock } from 'lucide-react';
import { useGuest } from '../lib/guest';

/** Pop-up shown when a guest tries something that needs an account (buy, sell, place an order, ...). */
export function AccountPrompt({ feature, onClose }: { feature?: string; onClose: () => void }) {
  const { goLogin } = useGuest();
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4 modal-overlay" style={{ background: 'rgba(2,6,16,0.78)' }} onClick={onClose}>
      <div className="w-full max-w-[380px] rounded-2xl border border-border p-6 text-center" style={{ background: 'var(--card)' }} onClick={e => e.stopPropagation()}>
        <div className="mx-auto mb-3 w-11 h-11 rounded-full flex items-center justify-center" style={{ background: 'rgba(0,200,255,0.12)' }}>
          <Lock className="w-5 h-5" style={{ color: 'var(--primary)' }} />
        </div>
        <p className="text-foreground font-bold" style={{ fontSize: 17 }}>Log in or create an account</p>
        <p className="text-muted-foreground mt-1.5" style={{ fontSize: 13.5, lineHeight: 1.5 }}>
          {feature ? `You need an account to ${feature}.` : 'You need an account to use this feature.'} It's free and takes a minute.
        </p>
        <div className="flex gap-2 mt-5">
          <button onClick={() => goLogin('login')} className="flex-1 py-2.5 rounded-xl font-bold border border-border text-foreground hover:bg-white/5" style={{ fontSize: 14 }}>Log in</button>
          <button onClick={() => goLogin('register')} className="flex-1 py-2.5 rounded-xl font-bold" style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}>Create account</button>
        </div>
        <button onClick={onClose} className="mt-3 text-muted-foreground hover:text-foreground" style={{ fontSize: 12.5 }}>Keep browsing</button>
      </div>
    </div>
  );
}

/** Stands in for a page that only makes sense with an account (My Portfolio, My Stats, Settings). */
export function AccountRequired({ title, text }: { title: string; text: string }) {
  const { goLogin } = useGuest();
  return (
    <div className="p-6 page-pad max-w-[1000px] mx-auto">
      <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>{title}</h1>
      <div className="rounded-2xl border border-border p-10 mt-5 text-center" style={{ background: 'var(--card)' }}>
        <div className="mx-auto mb-3 w-12 h-12 rounded-full flex items-center justify-center" style={{ background: 'rgba(0,200,255,0.12)' }}>
          <Lock className="w-5 h-5" style={{ color: 'var(--primary)' }} />
        </div>
        <p className="text-foreground font-semibold" style={{ fontSize: 17 }}>You need an account to use {title}</p>
        <p className="text-muted-foreground mt-1.5 mx-auto" style={{ fontSize: 13.5, maxWidth: 420, lineHeight: 1.5 }}>{text}</p>
        <div className="flex gap-2 justify-center mt-5">
          <button onClick={() => goLogin('login')} className="px-5 py-2.5 rounded-xl font-bold border border-border text-foreground hover:bg-white/5" style={{ fontSize: 14 }}>Log in</button>
          <button onClick={() => goLogin('register')} className="px-5 py-2.5 rounded-xl font-bold" style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}>Create account</button>
        </div>
      </div>
    </div>
  );
}
