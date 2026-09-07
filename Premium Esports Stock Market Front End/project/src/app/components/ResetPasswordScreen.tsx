import { useState } from 'react';
import { useAuth } from '../lib/auth';

// Rendered instead of the normal app whenever the URL has a
// `?reset_token=...` query param -- i.e. the user just clicked the link
// from their password-reset email (see app/services/password_reset_service.py
// for how that link is built). This app has no client-side router (see
// App.tsx), so this is a plain query-param check rather than a real route.
export function ResetPasswordScreen({ token }: { token: string }) {
  const { confirmPasswordReset } = useAuth();
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    if (newPassword.length < 8) {
      setLocalError('Password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmPasswordReset(token, newPassword);
      setDone(true);
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : 'That reset link is invalid or has expired.');
    } finally {
      setSubmitting(false);
    }
  }

  function goToLogin() {
    // Strips ?reset_token=... from the URL and reloads into the normal
    // login screen.
    window.location.href = window.location.origin + window.location.pathname;
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
          <p className="font-semibold mb-1" style={{ fontSize: 15, color: 'var(--foreground)' }}>Choose a new password</p>

          {done ? (
            <>
              <p className="text-muted-foreground mt-3 mb-4" style={{ fontSize: 13, lineHeight: 1.5 }}>
                Your password has been updated.
              </p>
              <button
                type="button"
                onClick={goToLogin}
                className="w-full py-3 rounded-xl font-bold transition-all"
                style={{ fontSize: 15, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
              >
                Log in
              </button>
            </>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3 mt-3">
              <div>
                <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>New password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                  style={{ background: 'var(--muted)', fontSize: 14 }}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </div>
              <div>
                <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>Confirm new password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
                  style={{ background: 'var(--muted)', fontSize: 14 }}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </div>

              {localError && <p style={{ fontSize: 12, color: 'var(--loss)' }}>{localError}</p>}

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
                {submitting ? 'Saving…' : 'Save new password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
