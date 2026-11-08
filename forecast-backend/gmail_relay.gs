/**
 * Forecast email relay. Runs as forecastesm@gmail.com and sends the emails the backend asks for.
 * Lets the backend send mail over HTTPS (Render's free plan blocks the normal SMTP ports).
 *
 * SET UP: see EMAIL_SETUP.md, section "Free plan: send through a Google Apps Script".
 *   1. Replace SECRET below with a long random string (and put the same string in Render as EMAIL_WEBHOOK_SECRET).
 *   2. Deploy > New deployment > Web app > Execute as: Me > Who has access: Anyone > Deploy. Copy the web app URL
 *      (it ends in /exec) into Render as EMAIL_WEBHOOK_URL.
 *
 * UPDATING THIS SCRIPT LATER: saving is NOT enough. The live URL keeps running the OLD code until you publish a new
 * version: Deploy > Manage deployments > pencil (edit) > Version: "New version" > Deploy. (The URL stays the same.)
 *
 * A normal Gmail account can send about 100 emails a day this way. The backend log shows how many are left.
 */
const SECRET = 'PASTE_A_LONG_RANDOM_STRING_HERE';

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (!SECRET || SECRET.indexOf('PASTE_') === 0 || String(d.secret || '').trim() !== SECRET.trim()) {
      return out_({ ok: false, error: 'forbidden' });
    }
    if (!d.to || !d.subject || !d.text) {
      return out_({ ok: false, error: 'missing fields' });
    }
    const left = MailApp.getRemainingDailyQuota();
    if (left < 1) {
      return out_({ ok: false, error: 'quota', remaining: 0 });
    }
    const opts = { name: d.from_name || 'Forecast' };
    if (d.html) opts.htmlBody = d.html;
    if (d.reply_to) opts.replyTo = d.reply_to;
    MailApp.sendEmail(d.to, d.subject, d.text, opts);
    return out_({ ok: true, remaining: left - 1 });
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  }
}

// Open the web app URL in a browser to check the deployment is public: you should see {"ok":true,"service":"forecast-email-relay"}.
// (If you see a Google sign-in page instead, "Who has access" is not set to Anyone.)
function doGet() {
  return out_({ ok: true, service: 'forecast-email-relay' });
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
