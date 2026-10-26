import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import type { Profile, SessionRow } from '../lib/types';
import { LegalModal, SUPPORT_EMAIL, type LegalDoc } from './LegalModal';
import { UserTag } from './UserTag';

const INPUT_CLS = 'w-full px-3 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50';
const INPUT_STYLE = { background: 'var(--muted)', fontSize: 14 } as const;

type Flash = { kind: 'ok' | 'err'; text: string } | null;

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
      <p className="font-semibold text-foreground" style={{ fontSize: 15 }}>{title}</p>
      {subtitle && <p className="text-muted-foreground mt-0.5 mb-3" style={{ fontSize: 12, lineHeight: 1.5 }}>{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </section>
  );
}

function FlashMsg({ flash }: { flash: Flash }) {
  if (!flash) return null;
  return <p className="mt-2" style={{ fontSize: 12, color: flash.kind === 'ok' ? 'var(--gain)' : 'var(--loss)' }}>{flash.text}</p>;
}

function Btn({ children, busy, danger, ...rest }: { busy?: boolean; danger?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      disabled={busy || rest.disabled}
      className="px-4 py-2.5 rounded-xl font-semibold transition-all disabled:opacity-50"
      style={{
        fontSize: 13,
        background: danger ? 'rgba(255,61,92,0.12)' : 'linear-gradient(135deg, var(--primary), var(--accent))',
        color: danger ? 'var(--loss)' : '#fff',
        border: danger ? '1px solid rgba(255,61,92,0.35)' : 'none',
      }}
    >
      {busy ? 'Please wait…' : children}
    </button>
  );
}

function errText(e: unknown, fallback = 'Something went wrong'): string {
  return e instanceof ApiError || e instanceof Error ? e.message : fallback;
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function shortAgent(ua: string | null): string {
  if (!ua) return 'Unknown device';
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return os ? `${browser} on ${os}` : browser;
}

export function SettingsPage() {
  const { refreshUser, logout } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [legal, setLegal] = useState<LegalDoc | null>(null);

  const load = useCallback(async () => {
    const [p, s] = await Promise.all([api.get<Profile>('/account/profile'), api.get<SessionRow[]>('/account/sessions').catch(() => [])]);
    setProfile(p);
    setSessions(s);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  // --- username ---
  const [name, setName] = useState('');
  const [nameBusy, setNameBusy] = useState(false);
  const [nameFlash, setNameFlash] = useState<Flash>(null);
  useEffect(() => { if (profile) setName(profile.display_name); }, [profile?.display_name]);

  async function saveName() {
    setNameBusy(true); setNameFlash(null);
    try {
      setProfile(await api.post<Profile>('/account/display-name', { display_name: name }));
      await refreshUser();
      setNameFlash({ kind: 'ok', text: 'Username updated.' });
    } catch (e) { setNameFlash({ kind: 'err', text: errText(e) }); }
    setNameBusy(false);
  }

  // --- tag ---
  const [tag, setTag] = useState('');
  const [tagColor, setTagColor] = useState('#00C8FF');
  const [tagBusy, setTagBusy] = useState(false);
  const [tagFlash, setTagFlash] = useState<Flash>(null);
  useEffect(() => { if (profile) { setTag(profile.tag ?? ''); setTagColor(profile.tag_color ?? profile.tag_colors[0] ?? '#00C8FF'); } }, [profile?.tag, profile?.tag_color]);

  async function saveTag(clear = false) {
    setTagBusy(true); setTagFlash(null);
    try {
      setProfile(await api.post<Profile>('/account/tag', { tag: clear ? null : tag || null, tag_color: tagColor }));
      await refreshUser();
      setTagFlash({ kind: 'ok', text: clear || !tag ? 'Tag removed.' : 'Tag saved.' });
      if (clear) setTag('');
    } catch (e) { setTagFlash({ kind: 'err', text: errText(e) }); }
    setTagBusy(false);
  }

  // --- password ---
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [newPw2, setNewPw2] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [pwFlash, setPwFlash] = useState<Flash>(null);

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwFlash(null);
    if (newPw !== newPw2) { setPwFlash({ kind: 'err', text: "New passwords don't match." }); return; }
    setPwBusy(true);
    try {
      const res = await api.post<{ access_token: string }>('/account/change-password', { current_password: curPw, new_password: newPw });
      await refreshUser(res.access_token);
      setCurPw(''); setNewPw(''); setNewPw2('');
      setPwFlash({ kind: 'ok', text: 'Password changed. Other devices were signed out.' });
    } catch (e2) { setPwFlash({ kind: 'err', text: errText(e2) }); }
    setPwBusy(false);
  }

  // --- email ---
  const [verifyCode, setVerifyCode] = useState('');
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyFlash, setVerifyFlash] = useState<Flash>(null);
  const [verifySent, setVerifySent] = useState(false);

  async function sendVerification() {
    setVerifyBusy(true); setVerifyFlash(null);
    try { await api.post('/auth/email/send-verification'); setVerifySent(true); setVerifyFlash({ kind: 'ok', text: 'Code sent — check your inbox.' }); }
    catch (e) { setVerifyFlash({ kind: 'err', text: errText(e) }); }
    setVerifyBusy(false);
  }
  async function confirmVerification() {
    setVerifyBusy(true); setVerifyFlash(null);
    try { await api.post('/auth/email/verify', { code: verifyCode.trim() }); setVerifyCode(''); setVerifySent(false); await load(); await refreshUser(); setVerifyFlash({ kind: 'ok', text: 'Email verified.' }); }
    catch (e) { setVerifyFlash({ kind: 'err', text: errText(e) }); }
    setVerifyBusy(false);
  }

  const [newEmail, setNewEmail] = useState('');
  const [emailPw, setEmailPw] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [emailStep, setEmailStep] = useState<'form' | 'code'>('form');
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailFlash, setEmailFlash] = useState<Flash>(null);

  async function requestEmailChange(e: React.FormEvent) {
    e.preventDefault();
    setEmailBusy(true); setEmailFlash(null);
    try { const r = await api.post<{ message: string }>('/account/email/request-change', { new_email: newEmail, password: emailPw }); setEmailStep('code'); setEmailFlash({ kind: 'ok', text: r.message }); }
    catch (e2) { setEmailFlash({ kind: 'err', text: errText(e2) }); }
    setEmailBusy(false);
  }
  async function confirmEmailChange() {
    setEmailBusy(true); setEmailFlash(null);
    try {
      setProfile(await api.post<Profile>('/account/email/confirm-change', { code: emailCode.trim() }));
      await refreshUser();
      setEmailStep('form'); setNewEmail(''); setEmailPw(''); setEmailCode('');
      setEmailFlash({ kind: 'ok', text: 'Email updated and verified.' });
    } catch (e) { setEmailFlash({ kind: 'err', text: errText(e) }); }
    setEmailBusy(false);
  }

  // --- delete ---
  const [delOpen, setDelOpen] = useState(false);
  const [delPw, setDelPw] = useState('');
  const [delConfirm, setDelConfirm] = useState('');
  const [delBusy, setDelBusy] = useState(false);
  const [delFlash, setDelFlash] = useState<Flash>(null);

  async function deleteAccount() {
    setDelBusy(true); setDelFlash(null);
    try { await api.post('/account/delete', { password: delPw, confirm: delConfirm }); logout(); }
    catch (e) { setDelFlash({ kind: 'err', text: errText(e) }); setDelBusy(false); }
  }

  if (!profile) {
    return <div className="p-6 max-w-[760px] mx-auto"><h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Settings</h1><p className="text-muted-foreground mt-3" style={{ fontSize: 14 }}>Loading…</p></div>;
  }

  const nameLocked = profile.name_change_available_at !== null;

  return (
    <div className="p-6 max-w-[760px] mx-auto space-y-5">
      <div>
        <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Settings</h1>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>Manage your profile, security and account.</p>
      </div>

      <Card title="Username" subtitle="Your public name on leaderboards. Inappropriate usernames will result in account deletion.">
        <div className="flex gap-2">
          <input value={name} onChange={e => setName(e.target.value)} maxLength={20} disabled={nameLocked} className={INPUT_CLS} style={INPUT_STYLE} />
          <Btn onClick={saveName} busy={nameBusy} disabled={nameLocked || name.trim() === profile.display_name}>Save</Btn>
        </div>
        <p className="text-muted-foreground mt-1.5" style={{ fontSize: 11 }}>
          3-20 characters: letters, numbers, _ . -  ·  You can change it once every {profile.name_change_cooldown_days} days
          {nameLocked && <> — next change available {fmtDateTime(profile.name_change_available_at)}</>}.
        </p>
        <FlashMsg flash={nameFlash} />
      </Card>

      <Card title="Tag" subtitle="An optional 2-5 character tag shown before your username on leaderboards, e.g. [FCST] name.">
        <div className="flex gap-2 items-center flex-wrap">
          <input value={tag} onChange={e => setTag(e.target.value.replace(/[^A-Za-z0-9]/g, '').slice(0, 5))} placeholder="TAG" className={INPUT_CLS + ' !w-28 font-mono uppercase'} style={INPUT_STYLE} />
          <div className="flex gap-1.5 flex-wrap">
            {profile.tag_colors.map(c => (
              <button
                key={c} onClick={() => setTagColor(c)} aria-label={`Color ${c}`}
                className="w-7 h-7 rounded-full transition-transform hover:scale-110"
                style={{ background: c, outline: tagColor.toUpperCase() === c ? '2px solid var(--foreground)' : '2px solid transparent', outlineOffset: 2 }}
              />
            ))}
          </div>
        </div>
        <p className="mt-3" style={{ fontSize: 14 }}>
          Preview: <span className="font-semibold text-foreground"><UserTag tag={tag.toUpperCase() || null} color={tagColor} />{profile.display_name}</span>
        </p>
        <div className="flex gap-2 mt-3">
          <Btn onClick={() => saveTag(false)} busy={tagBusy}>Save tag</Btn>
          {profile.tag && <Btn danger onClick={() => saveTag(true)} busy={tagBusy}>Remove tag</Btn>}
        </div>
        <FlashMsg flash={tagFlash} />
      </Card>

      <Card title="Email" subtitle="Used to sign in and to recover your account. Codes and security notices are sent from a no-reply address.">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="font-mono text-foreground" style={{ fontSize: 14 }}>{profile.email}</p>
          <span
            className="px-2 py-0.5 rounded-full font-bold"
            style={{ fontSize: 10, background: profile.email_verified ? 'rgba(16,217,160,0.12)' : 'rgba(251,191,36,0.14)', color: profile.email_verified ? 'var(--gain)' : '#fbbf24' }}
          >
            {profile.email_verified ? 'VERIFIED' : 'NOT VERIFIED'}
          </span>
        </div>

        {!profile.email_verified && (
          <div className="mt-3 rounded-xl p-3" style={{ background: 'var(--muted)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>Verify your email so you can always recover your account if you forget your password.</p>
            <div className="flex gap-2 mt-2 flex-wrap">
              {!verifySent ? (
                <Btn onClick={sendVerification} busy={verifyBusy}>Send verification code</Btn>
              ) : (
                <>
                  <input value={verifyCode} onChange={e => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder="6-digit code" className={INPUT_CLS + ' !w-40 font-mono'} style={INPUT_STYLE} />
                  <Btn onClick={confirmVerification} busy={verifyBusy} disabled={verifyCode.length < 6}>Verify</Btn>
                  <button onClick={sendVerification} className="text-muted-foreground" style={{ fontSize: 12 }}>Resend</button>
                </>
              )}
            </div>
            <FlashMsg flash={verifyFlash} />
          </div>
        )}

        <details className="mt-4">
          <summary className="cursor-pointer text-muted-foreground" style={{ fontSize: 13 }}>Change email</summary>
          {emailStep === 'form' ? (
            <form onSubmit={requestEmailChange} className="space-y-2 mt-3">
              <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="New email address" className={INPUT_CLS} style={INPUT_STYLE} required />
              <input type="password" value={emailPw} onChange={e => setEmailPw(e.target.value)} placeholder="Current password" className={INPUT_CLS} style={INPUT_STYLE} autoComplete="current-password" required />
              <Btn busy={emailBusy} type="submit">Send confirmation code</Btn>
            </form>
          ) : (
            <div className="flex gap-2 mt-3 flex-wrap">
              <input value={emailCode} onChange={e => setEmailCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder="6-digit code" className={INPUT_CLS + ' !w-40 font-mono'} style={INPUT_STYLE} />
              <Btn onClick={confirmEmailChange} busy={emailBusy} disabled={emailCode.length < 6}>Confirm</Btn>
              <button onClick={() => setEmailStep('form')} className="text-muted-foreground" style={{ fontSize: 12 }}>Back</button>
            </div>
          )}
          <FlashMsg flash={emailFlash} />
        </details>
      </Card>

      <Card title="Password" subtitle="You'll need your current password. Changing it signs you out everywhere else.">
        <form onSubmit={savePassword} className="space-y-2">
          <input type="password" value={curPw} onChange={e => setCurPw(e.target.value)} placeholder="Current password" className={INPUT_CLS} style={INPUT_STYLE} autoComplete="current-password" required />
          <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="New password" className={INPUT_CLS} style={INPUT_STYLE} autoComplete="new-password" minLength={8} required />
          <input type="password" value={newPw2} onChange={e => setNewPw2(e.target.value)} placeholder="Confirm new password" className={INPUT_CLS} style={INPUT_STYLE} autoComplete="new-password" minLength={8} required />
          <p className="text-muted-foreground" style={{ fontSize: 11 }}>At least 8 characters, with a letter and a number.</p>
          <Btn busy={pwBusy} type="submit">Change password</Btn>
        </form>
        <FlashMsg flash={pwFlash} />
      </Card>

      <Card title="Recent activity" subtitle="Your latest sessions. If you see something you don't recognize, change your password.">
        {sessions.length === 0 ? (
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>No sessions recorded yet.</p>
        ) : (
          <div className="space-y-1.5">
            {sessions.slice(0, 8).map((s, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg" style={{ background: 'var(--muted)' }}>
                <div>
                  <p className="text-foreground" style={{ fontSize: 13 }}>{shortAgent(s.user_agent)}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>{fmtDateTime(s.started_at)}{s.ip_address ? ` · ${s.ip_address}` : ''}</p>
                </div>
                <p className="text-muted-foreground font-mono" style={{ fontSize: 11 }}>{s.active_minutes} min</p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Help & legal">
        <div className="flex gap-4 flex-wrap" style={{ fontSize: 13 }}>
          <button onClick={() => setLegal('terms')} style={{ color: 'var(--primary)' }}>Terms of Service</button>
          <button onClick={() => setLegal('privacy')} style={{ color: 'var(--primary)' }}>Privacy Policy</button>
          <a href={`mailto:${SUPPORT_EMAIL}`} style={{ color: 'var(--primary)' }}>Contact support ({SUPPORT_EMAIL})</a>
        </div>
      </Card>

      <section className="rounded-2xl border p-5" style={{ borderColor: 'rgba(255,61,92,0.3)', background: 'rgba(255,61,92,0.04)' }}>
        <p className="font-semibold" style={{ fontSize: 15, color: 'var(--loss)' }}>Delete account</p>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12, lineHeight: 1.5 }}>
          Permanently removes your personal data and signs you out. Your open orders are cancelled; anonymized trade history stays in the market record. This can't be undone.
        </p>
        {!delOpen ? (
          <div className="mt-3"><Btn danger onClick={() => setDelOpen(true)}>Delete my account…</Btn></div>
        ) : (
          <div className="space-y-2 mt-3">
            <input type="password" value={delPw} onChange={e => setDelPw(e.target.value)} placeholder="Your password" className={INPUT_CLS} style={INPUT_STYLE} autoComplete="current-password" />
            <input value={delConfirm} onChange={e => setDelConfirm(e.target.value)} placeholder='Type DELETE to confirm' className={INPUT_CLS} style={INPUT_STYLE} />
            <div className="flex gap-2">
              <Btn danger busy={delBusy} onClick={deleteAccount} disabled={!delPw || delConfirm.trim().toUpperCase() !== 'DELETE'}>Permanently delete</Btn>
              <button onClick={() => { setDelOpen(false); setDelPw(''); setDelConfirm(''); }} className="text-muted-foreground" style={{ fontSize: 12 }}>Cancel</button>
            </div>
            <FlashMsg flash={delFlash} />
          </div>
        )}
      </section>

      {legal && <LegalModal doc={legal} onClose={() => setLegal(null)} />}
    </div>
  );
}
