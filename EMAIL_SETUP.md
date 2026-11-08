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


## Free plan: send through a Google Apps Script (no SMTP needed)

Render's free web services block the SMTP ports, so Gmail SMTP won't work there. This sends through the Gmail account over
HTTPS instead (EMAIL_PROVIDER=webhook). About 100 emails a day for a normal Gmail account.

1. Sign in to forecastesm@gmail.com, open https://script.google.com, **New project**.
2. Delete the sample code, paste in `forecast-backend/gmail_relay.gs`, and replace `PASTE_A_LONG_RANDOM_STRING_HERE` with a
   long random string (30+ characters). Save.
3. **Deploy > New deployment > Web app**. Execute as: **Me**. Who has access: **Anyone**. Deploy, and approve the permission
   prompt ("Advanced" > "Go to ... (unsafe)" > Allow; it only needs to send mail as you). Copy the web app URL.
4. In Render (`forecast-backend` > Environment) set: `EMAIL_PROVIDER=webhook`, `EMAIL_WEBHOOK_URL` = the URL,
   `EMAIL_WEBHOOK_SECRET` = the same random string, `EMAIL_FROM_ADDRESS=Forecast <forecastesm@gmail.com>`,
   `EMAIL_REPLY_TO=forecastesm@gmail.com`.
5. Use "Forgot password" on the site and check the inbox (and Spam).

### Check the relay is public
Open the web app URL (the one ending in `/exec`) in a browser. You should see `{"ok":true,"service":"forecast-email-relay"}`.
A Google sign-in page means "Who has access" is not **Anyone**.

### Updating the script later
Saving in the Apps Script editor is **not** enough: the live URL keeps running the old code. Publish it:
**Deploy > Manage deployments > pencil (edit) > Version: New version > Deploy**. The URL stays the same.

### Test the live site's email (no guessing)
The backend can send itself a test through exactly the path "Forgot password" uses, and shows the real error if it fails.
In PowerShell (replace the email/password with your admin login and an address you can read):
```powershell
$api = "https://forecast-backend-vfje.onrender.com/api/v1"
$tok = (Invoke-RestMethod -Method Post "$api/auth/login" -ContentType "application/json" -Body '{"email":"ADMIN_EMAIL","password":"ADMIN_PASSWORD"}').access_token
Invoke-RestMethod -Method Post "$api/admin/email/test?to=you@gmail.com" -Headers @{Authorization="Bearer $tok"}
```
You get back `provider`, `configured`, `sent` and `error`. `sent: True` means Google accepted it; if it still isn't in the
inbox, check Spam. `error` text says exactly what's wrong (wrong secret, relay not public, daily limit, ...).

### If codes don't arrive: where to look (Render > forecast-backend > Logs)
| Log line | Meaning / fix |
|---|---|
| `Email: NOT CONFIGURED` at startup | `EMAIL_PROVIDER` (or its URL/secret) is missing or misspelled in Render's Environment. |
| `email relay refused the message: forbidden` | `EMAIL_WEBHOOK_SECRET` in Render differs from `SECRET` in the Apps Script. |
| `email relay did not return JSON` | The URL isn't the `/exec` web app URL, or "Who has access" isn't Anyone. |
| `...hit its daily sending limit` | Gmail allows ~100 sends/day. It resets within 24 hours; move to Resend + your own domain for more. |
| `Email relay: N sends left` (warning at 20 or fewer) | You're close to the daily limit. |
| `Email (...) FAILED after 3 attempts` | The code was discarded (so it doesn't count against the person's hourly limit); they can ask again. |

How sending works now: "Send code" answers instantly, then the email is sent in the background with up to 3 attempts. A
failed send is thrown away rather than counted, so a mail outage can't lock anyone out.
