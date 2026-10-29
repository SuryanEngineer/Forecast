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

---

# Option B — Gmail (a dedicated Gmail account), full walkthrough

Use this if you don't have a domain yet. It sends the site's emails (verification codes, forgot-password codes, notices) from a
Gmail address. **It needs the backend on a paid Render plan** (Render's free plan blocks the SMTP port), and Gmail limits how many
messages one account can send per day (fine for launch). Until this is set up, `EMAIL_PROVIDER` stays `console`: **forgot-password
does not work for real users** (the code only shows in the Render logs).

### 1. Create the dedicated Gmail account
1. Go to accounts.google.com → Create account. Pick a name that looks official, e.g. `forecastfantasy.support@gmail.com`.
2. Use a strong password stored in a password manager. This account will own your support inbox, so use a recovery phone/email you control.

### 2. Turn on 2-Step Verification (required for App Passwords)
1. Signed in to that account: myaccount.google.com → **Security** → **2-Step Verification** → turn it on.

### 3. Create an App Password
1. myaccount.google.com → search **App passwords** (or Security → 2-Step Verification → App passwords at the bottom).
2. Name it `Forecast` → **Create**. Google shows a 16-character code like `abcd efgh ijkl mnop`.
3. Copy it **without spaces** (`abcdefghijklmnop`). It is shown once. Never commit it or paste it in chat.

### 4. Test it on your computer first
1. `cd forecast-backend` → `notepad .env` and add (replace with your account and App Password):
   ```
   EMAIL_PROVIDER=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=forecastfantasy.support@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop
   EMAIL_FROM_ADDRESS=Forecast <forecastfantasy.support@gmail.com>
   EMAIL_REPLY_TO=forecastfantasy.support@gmail.com
   SUPPORT_EMAIL=forecastfantasy.support@gmail.com
   ```
2. `python3 scripts/send_test_email.py you@yourpersonalemail.com` → the email should arrive (check spam).
   An "authentication" error means a wrong App Password or 2-Step Verification is off.
3. **Remove or comment out those lines in your local `.env` afterwards if you don't want local runs sending real email.**

### 5. Put the backend on a paid plan
Render dashboard → `forecast-backend` → **Settings** → **Instance Type** → choose the cheapest paid option (Starter).

### 6. Set the variables on Render
`forecast-backend` → **Environment** → add/edit these, then Save (it redeploys):
```
EMAIL_PROVIDER      = smtp
SMTP_HOST           = smtp.gmail.com
SMTP_PORT           = 587
SMTP_USERNAME       = (your Gmail address)
SMTP_PASSWORD       = (the 16-character App Password)
EMAIL_FROM_ADDRESS  = Forecast <your Gmail address>
EMAIL_REPLY_TO      = (your Gmail address)
SUPPORT_EMAIL       = (your Gmail address)
```
Also set `VITE_SUPPORT_EMAIL` on `forecast-frontend` → Environment to the same address (shown in Terms, Privacy and Settings).

### 7. Test on the live site
Log out → **Forgot password** → enter a real account's email → the 6-digit code should arrive in that inbox. Also try registering a
new account: a verification email should arrive.

### Later: move to your own domain
Once you buy a domain, switch to Option A above (Resend) so mail comes from `no-reply@yourdomain.com` with proper SPF/DKIM/DMARC.
