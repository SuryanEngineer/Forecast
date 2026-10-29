import { X } from 'lucide-react';

export type LegalDoc = 'terms' | 'privacy';

export const SUPPORT_EMAIL: string = (import.meta as any).env?.VITE_SUPPORT_EMAIL || 'support@forecast.gg';

const UPDATED = 'October 26, 2026';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <p className="font-semibold mb-1.5" style={{ fontSize: 14, color: 'var(--foreground)' }}>{title}</p>
      <div className="text-muted-foreground space-y-2" style={{ fontSize: 13, lineHeight: 1.65 }}>{children}</div>
    </div>
  );
}

function Terms() {
  return (
    <>
      <Section title="1. What Forecast is">
        <p>Forecast is a free fantasy game where you trade virtual shares of professional Fortnite players using virtual cash. All money on Forecast is fictional: it has no cash value, can't be bought, withdrawn, or exchanged for anything of real-world value, and nothing here is investment advice.</p>
        <p>Forecast is an independent fan project. It is not affiliated with, endorsed by, or sponsored by Epic Games, Fortnite, or any player or team shown on the site. Player names and results are used for informational and entertainment purposes.</p>
      </Section>
      <Section title="2. Your account">
        <p>You must provide a valid email address and keep your password private. You're responsible for activity on your account. One account per person, please; accounts used to manipulate rankings (multi-accounting, collusion, or exploiting bugs) may be reset or removed.</p>
      </Section>
      <Section title="3. Usernames and conduct">
        <p>Usernames and tags must be appropriate for a general audience. Names that are offensive, hateful, sexual, harassing, or that impersonate other people or staff will result in account deletion without notice. Don't attempt to disrupt the service, scrape it aggressively, or access other users' accounts.</p>
      </Section>
      <Section title="4. Game rules and changes">
        <p>Prices, dividends, fees, seasons, ranks, and points are game mechanics that we may tune, correct, or reset at any time to keep the game fair, including correcting errors in tournament data. Seasonal points and ranks reset every season by design.</p>
      </Section>
      <Section title="5. Availability and liability">
        <p>The service is provided "as is" without warranties. We don't guarantee uninterrupted or error-free operation, and to the fullest extent permitted by law we're not liable for any loss arising from your use of Forecast, which involves only virtual items.</p>
      </Section>
      <Section title="6. Deleting your account">
        <p>You can delete your account at any time from Settings. Your personal data is removed; anonymized trade records may be kept so the game's market history stays consistent.</p>
      </Section>
      <Section title="7. Contact">
        <p>Questions about these terms: {SUPPORT_EMAIL}.</p>
      </Section>
    </>
  );
}

function Privacy() {
  return (
    <>
      <Section title="What we collect">
        <p>Account data: your email address, username, optional tag, and a securely hashed password (we never store your password in readable form).</p>
        <p>Game data: your orders, trades, holdings, balances, rankings, and achievements.</p>
        <p>Usage data: when you log in, how long and how often you use the site (session activity), and your IP address and browser type for security and abuse prevention. We use this to run and improve the game and to protect accounts.</p>
      </Section>
      <Section title="How we use it">
        <p>To operate your account, show leaderboards, send account emails (password-reset codes, security notices), keep the service secure, and understand how the game is used so we can improve it. We don't send marketing email unless you opt in, and we don't sell your personal data.</p>
      </Section>
      <Section title="What others can see">
        <p>Your username, tag, rank, and portfolio standings appear on public leaderboards and may be viewable by other players. Your email is never shown to other users.</p>
      </Section>
      <Section title="Email">
        <p>Account emails come from a no-reply address. If you didn't request a code, you can ignore it. Replies to the no-reply address aren't monitored; contact {SUPPORT_EMAIL} for help.</p>
      </Section>
      <Section title="Storage, retention and your choices">
        <p>Data is stored with our hosting and database providers. You can change your username, email, and password in Settings, and delete your account there too; deletion removes your personal data (email, name, session details) and anonymizes your remaining game history.</p>
      </Section>
      <Section title="Contact">
        <p>Privacy questions or data requests: {SUPPORT_EMAIL}.</p>
      </Section>
    </>
  );
}

export function LegalModal({ doc, onClose }: { doc: LegalDoc; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" style={{ background: 'rgba(2,6,16,0.78)' }} onClick={onClose}>
      <div
        className="w-full max-w-[640px] max-h-[85vh] rounded-2xl border border-border flex flex-col"
        style={{ background: 'var(--card)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <p className="font-bold" style={{ fontSize: 17, color: 'var(--foreground)' }}>
              {doc === 'terms' ? 'Terms of Service' : 'Privacy Policy'}
            </p>
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>Last updated {UPDATED}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5 overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
          {doc === 'terms' ? <Terms /> : <Privacy />}
        </div>
      </div>
    </div>
  );
}
