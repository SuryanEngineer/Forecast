import { useState } from 'react';
import { useAuth } from '../lib/auth';
import { LegalModal, type LegalDoc } from './LegalModal';

const INPUT_CLS = 'w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50';
const INPUT_STYLE = { background: 'var(--muted)', fontSize: 14 } as const;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="min-h-screen w-screen flex items-center justify-center py-8"
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
        {children}
      </div>
    </div>
  );
}

function Field({ label, ...rest }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label className="text-muted-foreground block mb-1.5" style={{ fontSize: 12 }}>{label}</label>
      <input {...rest} className={INPUT_CLS} style={INPUT_STYLE} />
    </div>
  );
}

function SubmitButton({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full py-3 rounded-xl font-bold transition-all mt-2"
      style={{
        fontSize: 15,
        background: busy ? 'rgba(255,255,255,0.08)' : 'linear-gradient(135deg, var(--primary), var(--accent))',
        color: busy ? 'var(--muted-foreground)' : '#fff',
      }}
    >
      {children}
    </button>
  );
}

export function AuthScreen() {
  const { login, register, requestPasswordReset, confirmPasswordReset, error } = useAuth();
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [legal, setLegal] = useState<LegalDoc | null>(null);

  // forgot-password flow: 'email' -> 'code' -> 'done'
  const [forgotStep, setForgotStep] = useState<'email' | 'code' | 'done'>('email');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [notice, setNotice] = useState<string | null>(null);

  function switchMode(m: 'login' | 'register' | 'forgot') {
    setMode(m);
    setLocalError(null);
    setNotice(null);
    setForgotStep('email');
    setCode('');
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else if (mode === 'register') {
        if (!displayName.trim()) throw new Error('Choose a username');
        if (!acceptTerms) throw new Error('Please accept the Terms of Service and Privacy Policy');
        await register(email, password, displayName.trim(), acceptTerms);
      } else if (forgotStep === 'email') {
        const msg = await requestPasswordReset(email);
        setNotice(msg);
        setForgotStep('code');
      } else {
        if (newPassword !== confirmPassword) throw new Error("Passwords don't match");
        await confirmPasswordReset(email, code.trim(), newPassword);
        setForgotStep('done');
      }
    } catch (err) {
      // useAuth().error already holds API errors; surface plain Errors (validation) locally
      if (err instanceof Error && !(err as any).status) setLocalError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const shownError = localError || error;

  if (mode === 'forgot') {
    return (
      <Shell>
        <div className="rounded-2xl border border-border p-6" style={{ background: 'var(--card)' }}>
          <p className="font-semibold mb-1" style={{ fontSize: 15, color: 'var(--foreground)' }}>Reset your password</p>

          {forgotStep === 'done' ? (
            <>
              <p className="text-muted-foreground mt-3 mb-4" style={{ fontSize: 13, lineHeight: 1.5 }}>
                Your password has been updated. Log in with your new password.
              </p>
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="w-full py-3 rounded-xl font-bold"
                style={{ fontSize: 15, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
              >
                Log in
              </button>
            </>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3 mt-2">
              {forgotStep === 'email' ? (
                <>
                  <p className="text-muted-foreground" style={{ fontSize: 13, lineHeight: 1.5 }}>
                    Enter the email on your account and we'll send a 6-digit code to reset your password.
                  </p>
                  <Field label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required />
                </>
              ) : (
                <>
                  <p className="text-muted-foreground" style={{ fontSize: 13, lineHeight: 1.5 }}>
                    {notice} Check your inbox (and spam folder) for an email from Forecast.
                  </p>
                  <Field
                    label="6-digit code" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    inputMode="numeric" autoComplete="one-time-code" placeholder="123456" required
                  />
                  <Field label="New password" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} autoComplete="new-password" minLength={8} required />
                  <Field label="Confirm new password" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} autoComplete="new-password" minLength={8} required />
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>At least 8 characters, with a letter and a number.</p>
                </>
              )}
              {shownError && <p style={{ fontSize: 12, color: 'var(--loss)' }}>{shownError}</p>}
              <SubmitButton busy={submitting}>
                {submitting ? 'Please wait…' : forgotStep === 'email' ? 'Send code' : 'Reset password'}
              </SubmitButton>
              {forgotStep === 'code' && (
                <button type="button" onClick={() => { setForgotStep('email'); setLocalError(null); }} className="w-full text-center" style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>
                  Didn't get it? Send a new code
                </button>
              )}
            </form>
          )}

          {forgotStep !== 'done' && (
            <button type="button" onClick={() => switchMode('login')} className="w-full text-center mt-4" style={{ fontSize: 12, color: 'var(--primary)' }}>
              Back to log in
            </button>
          )}
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="rounded-2xl border border-border p-6" style={{ background: 'var(--card)' }}>
        <div className="flex rounded-xl overflow-hidden border border-border mb-5">
          {(['login', 'register'] as const).map(m => (
            <button
              key={m}
              type="button"
              onClick={() => switchMode(m)}
              className="flex-1 py-2.5 font-semibold transition-all"
              style={{
                fontSize: 13,
                background: mode === m ? (m === 'login' ? 'rgba(0,200,255,0.1)' : 'rgba(155,111,255,0.1)') : 'transparent',
                color: mode === m ? (m === 'login' ? 'var(--primary)' : 'var(--accent)') : 'var(--muted-foreground)',
              }}
            >
              {m === 'login' ? 'Log In' : 'Create Account'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === 'register' && (
            <div>
              <Field label="Username" value={displayName} onChange={e => setDisplayName(e.target.value)} maxLength={20} autoComplete="username" required />
              <p className="text-muted-foreground mt-1.5" style={{ fontSize: 11, lineHeight: 1.45 }}>
                3-20 characters (letters, numbers, _ . -). Inappropriate usernames will result in account deletion.
              </p>
            </div>
          )}
          <Field label="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required />
          <Field
            label="Password" type="password" value={password} onChange={e => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required
          />
          {mode === 'register' && (
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>At least 8 characters, with a letter and a number.</p>
          )}

          {mode === 'login' && (
            <button type="button" onClick={() => switchMode('forgot')} className="block ml-auto" style={{ fontSize: 12, color: 'var(--primary)' }}>
              Forgot password?
            </button>
          )}

          {mode === 'register' && (
            <label className="flex items-start gap-2 cursor-pointer" style={{ fontSize: 12, lineHeight: 1.45, color: 'var(--muted-foreground)' }}>
              <input type="checkbox" checked={acceptTerms} onChange={e => setAcceptTerms(e.target.checked)} className="mt-0.5" />
              <span>
                I agree to the{' '}
                <button type="button" onClick={() => setLegal('terms')} style={{ color: 'var(--primary)' }}>Terms of Service</button>
                {' '}and{' '}
                <button type="button" onClick={() => setLegal('privacy')} style={{ color: 'var(--primary)' }}>Privacy Policy</button>.
              </span>
            </label>
          )}

          {shownError && <p style={{ fontSize: 12, color: 'var(--loss)' }}>{shownError}</p>}

          {mode === 'register' && (
            <p className="text-muted-foreground" style={{ fontSize: 11, lineHeight: 1.5 }}>
              New accounts start with fantasy cash to invest. No real money is ever involved.
            </p>
          )}

          <SubmitButton busy={submitting}>
            {submitting ? 'Please wait…' : mode === 'login' ? 'Log In' : 'Create Account'}
          </SubmitButton>
        </form>
      </div>

      <p className="text-center text-muted-foreground mt-4" style={{ fontSize: 11 }}>
        <button type="button" onClick={() => setLegal('terms')} className="hover:underline">Terms</button>
        {' · '}
        <button type="button" onClick={() => setLegal('privacy')} className="hover:underline">Privacy</button>
      </p>
      {legal && <LegalModal doc={legal} onClose={() => setLegal(null)} />}
    </Shell>
  );
}
