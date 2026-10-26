# Account email setup (verification + forgot-password codes)

Forecast emails a **6-digit code** for: forgot password, verifying an email, and changing an email. It also sends short
security notices (password changed, email changed, account deleted). Until you configure a provider, emails are **not
sent** — the code is only printed in the server terminal (fine for local development, not for real users).

The goal: mail that comes from a **no-reply address on your own domain**, passes SPF/DKIM/DMARC (so it lands in the
inbox, not spam), and has a **real support address** in the footer / Reply-To so people know it's legitimate.

## 1. Get a domain (one-time, ~$10/year)
Buy something like `forecast.gg` / `forecastfantasy.com` from Cloudflare Registrar, Namecheap, or Porkbun. A free
`onrender.com` address cannot send trusted email — you need your own domain.

## 2. Pick a provider (recommended: Resend)
| Provider | Free tier | Works on Render free? | Notes |
|---|---|---|---|
| **Resend** (recommended) | 3,000/mo (100/day) | **Yes** (HTTPS API) | `EMAIL_PROVIDER=resend` |
| Brevo / Mailgun / SES / Zoho (SMTP) | varies | **No** — Render's free tier blocks SMTP ports | `EMAIL_PROVIDER=smtp`, fine on a paid host/VPS |

### Resend, step by step
1. Sign up at resend.com → **Domains → Add Domain** → enter your domain.
2. Resend shows ~3 DNS records (SPF `TXT`, DKIM `TXT`/`CNAME`, optionally MX for bounces). Add them at your DNS host
   (Cloudflare → DNS). Click **Verify** (can take a few minutes).
3. Add a **DMARC** record at your DNS host (one `TXT` record):
   - Name: `_dmarc`  Value: `v=DMARC1; p=none; rua=mailto:you@yourdomain.com`
   - After a couple of weeks of clean delivery you can tighten to `p=quarantine`.
4. **API Keys → Create** → copy the key (starts with `re_`).

## 3. Make a real support inbox (free)
In Cloudflare → **Email → Email Routing** (free): create `support@yourdomain.com` and forward it to your personal email.
Now replies and "contact support" mail reach you, while the sender address (`no-reply@…`) stays automated.

## 4. Configure the backend
Local `.env` (forecast-backend) **and** Render → forecast-backend → Environment:

```
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxx
EMAIL_FROM_ADDRESS=Forecast <no-reply@yourdomain.com>
EMAIL_REPLY_TO=support@yourdomain.com
SUPPORT_EMAIL=support@yourdomain.com
```

Frontend (Render static site → Environment, or `.env`): `VITE_SUPPORT_EMAIL=support@yourdomain.com`
(shown in Terms, Privacy and Settings).

## 5. Test before real users depend on it
```powershell
cd forecast-backend
python3 scripts/send_test_email.py you@gmail.com
```
Check: it arrives in the **inbox**, the sender shows **Forecast**, and "Reply" goes to your support address. In Gmail
→ ⋮ → **Show original** you should see `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`.

## How the protection works
- Codes are random, stored hashed, expire in 15 minutes, work once, and burn after 5 wrong guesses.
- "Forgot password" answers identically whether or not the email has an account.
- Resending is rate-limited (per-user minimum gap + hourly cap).
- Logins lock for 15 minutes after 8 wrong passwords.
- Resetting or changing a password signs out every other device.
