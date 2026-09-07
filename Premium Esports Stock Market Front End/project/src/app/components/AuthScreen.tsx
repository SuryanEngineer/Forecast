import { useState } from 'react';
import { useAuth } from '../lib/auth';

export function AuthScreen() {
  const { login, register, requestPasswordReset, error } = useAuth();
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [forgotSent, setForgotSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else if (mode === 'register') {
        if (!displayName.trim()) {
          setLocalError('Enter a display name');
          setSubmitting(false);
          return;
        }
        await register(email, password, displayName.trim());
      } else {
        await requestPasswordReset(email);
        setForgotSent(true);
      }
    } catch {
      // error already surfaced via useAuth().error
    } finally {
      setSubmitting(false);
    }
  }

  if (mode === 'forgot') {
    return (
      <div
        className="h-screen w-screen flex items-center justify-center"
        style={{
          background:
            'radial-gradient(ellipse at 15% 50%, rgba(0,200,255,0.05) 0%, transparent 55%), radial-gradient(ellipse at 85% 15%, rgba(155,111,255,0.06) 0%, transparent 50%), var(--background)',
        }}
      >
        <div className="w-full max-w-[380px] px-6">
          <div className="flex items-center gap-3 mb-8 justify-center">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
              style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}
            >
              <span className="font-mono font-bold" style={{ fontSize: 16, color: '#020610' }}>F</span>
            </div>
            <div>
              <p className="font-bold tracking-wider" style={{ fontSize: 16, color: 'var(--foreground)' }}>FORECAST</p>
              <p className="text-muted-foreground" style={{ fontSize: 11 }}>Esports Markets</p>
            </div>
          </div>

          <div className="rounded-2xl border border-border p-6" style={{ background: 'var(--card)' }}>
            <p className="font-semibold mb-1" style={{ fontSize: 15, color: 'var(--foreground)' }}>Reset your password</p>

            {forgotSent ? (
              <p className="text-muted-foreground mt-3" style={{ fontSize: 13, lineHeight: 1.5 }}>
                If that email has an account, a reset link is on its way. Check your inbox (and spam folder) --
                the link expires in 30 minutes.
              </p>
            ) : (
              <>
                <p className="text-muted-foreground mb-4" style={{ fontSize: 13, lineHeight: 1.5 }}>
                  Enter the email on your account and we'll send a link to reset your password.
                </p>
                <form onSubmit={handleSubmit} className="space-y-3">
                  <div>
                    <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Email</label>
                    <input
                      type="email"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                      style={{ background: 'var(--muted)', fontSize: 14 }}
                      autoComplete="email"
                      required
                    />
                  </div>
                  {(error || localError) && (
                    <p style={{ fontSize: 12, color: 'var(--loss)' }}>{localError || error}</p>
                  )}
                  <button
                    type="submit"
                    disabled={submitting}
                    className="w-full py-3 rounded-xl font-bold transition-all mt-2"
                    style={{
                      fontSize: 15,
                      background: submitting ? 'rgba(255,255,255,0.08)' : 'linear-gradient(135deg, var(--primary), var(--accent))',
                      color: submitting ? 'var(--muted-foreground)' : '#fff',
                    }}
                  >
                    {submitting ? 'Sending…' : 'Send reset link'}
                  </button>
                </form>
              </>
            )}

            <button
              type="button"
              onClick={() => { setMode('login'); setForgotSent(false); }}
              className="w-full text-center mt-4"
              style={{ fontSize: 12, color: 'var(--primary)' }}
            >
              Back to log in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="h-screen w-screen flex items-center justify-center"
      style={{
        background:
          'radial-gradient(ellipse at 15% 50%, rgba(0,200,255,0.05) 0%, transparent 55%), radial-gradient(ellipse at 85% 15%, rgba(155,111,255,0.06) 0%, transparent 50%), var(--background)',
      }}
    >
      <div className="w-full max-w-[380px] px-6">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}
          >
            <span className="font-mono font-bold" style={{ fontSize: 16, color: '#020610' }}>F</span>
          </div>
          <div>
            <p className="font-bold tracking-wider" style={{ fontSize: 16, color: 'var(--foreground)' }}>FORECAST</p>
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>Esports Markets</p>
          </div>
        </div>

        <div className="rounded-2xl border border-border p-6" style={{ background: 'var(--card)' }}>
          <div className="flex rounded-xl overflow-hidden border border-border mb-5">
            <button
              type="button"
              onClick={() => setMode('login')}
              className="flex-1 py-2.5 font-semibold transition-all"
              style={{
                fontSize: 13,
                background: mode === 'login' ? 'rgba(0,200,255,0.1)' : 'transparent',
                color: mode === 'login' ? 'var(--primary)' : 'var(--muted-foreground)',
              }}
            >
              Log In
            </button>
            <button
              type="button"
              onClick={() => setMode('register')}
              className="flex-1 py-2.5 font-semibold transition-all"
              style={{
                fontSize: 13,
                background: mode === 'register' ? 'rgba(155,111,255,0.1)' : 'transparent',
                color: mode === 'register' ? 'var(--accent)' : 'var(--muted-foreground)',
              }}
            >
              Create Account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {mode === 'register' && (
              <div>
                <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Display name</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                  style={{ background: 'var(--muted)', fontSize: 14 }}
                  required
                />
              </div>
            )}
            <div>
              <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                style={{ background: 'var(--muted)', fontSize: 14 }}
                autoComplete="email"
                required
              />
            </div>
            <div>
              <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                style={{ background: 'var(--muted)', fontSize: 14 }}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength={8}
                required
              />
            </div>

            {mode === 'login' && (
              <button
                type="button"
                onClick={() => setMode('forgot')}
                className="block ml-auto"
                style={{ fontSize: 12, color: 'var(--primary)' }}
              >
                Forgot password?
              </button>
            )}

            {(error || localError) && (
              <p style={{ fontSize: 12, color: 'var(--loss)' }}>{localError || error}</p>
            )}

            {mode === 'register' && (
              <p className="text-muted-foreground" style={{ fontSize: 11, lineHeight: 1.5 }}>
                New accounts start with $1,000,000 in fantasy cash to invest.
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3 rounded-xl font-bold transition-all mt-2"
              style={{
                fontSize: 15,
                background: submitting ? 'rgba(255,255,255,0.08)' : 'linear-gradient(135deg, var(--primary), var(--accent))',
                color: submitting ? 'var(--muted-foreground)' : '#fff',
              }}
            >
              {submitting ? 'Please wait…' : mode === 'login' ? 'Log In' : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-muted-foreground mt-4" style={{ fontSize: 12 }}>
          Connects to your local Forecast API server. See README_SETUP.md if it can't connect.
        </p>
      </div>
    </div>
  );
}
