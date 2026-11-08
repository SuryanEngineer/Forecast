"""
Unit tests for the email delivery layer (app/services/email_service.py): provider-name cleanup, "is it really
configured", the retry helper, and how the Google Apps Script relay's replies are handled.

Runs with plain pytest OR `python3 tests/test_email_delivery.py`. It needs no database and no network: the module is
loaded straight from its file with a stub `settings` and a stub `httpx`, so it works even where the app's
dependencies aren't installed.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Settings:
    EMAIL_PROVIDER = "console"
    EMAIL_FROM_ADDRESS = "Forecast <forecastesm@gmail.com>"
    EMAIL_REPLY_TO = None
    SUPPORT_EMAIL = "forecastesm@gmail.com"
    EMAIL_CODE_EXPIRE_MINUTES = 15
    SMTP_HOST = None
    SMTP_PORT = 587
    SMTP_USERNAME = None
    SMTP_PASSWORD = None
    SMTP_USE_SSL = False
    EMAIL_WEBHOOK_URL = None
    EMAIL_WEBHOOK_SECRET = None
    RESEND_API_KEY = None


class _Resp:
    def __init__(self, data=None, *, json_error=False, status_error=None):
        self._data, self._json_error, self._status_error = data, json_error, status_error

    def raise_for_status(self):
        if self._status_error:
            raise RuntimeError(self._status_error)

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._data


def _load():
    """Fresh copy of email_service wired to stubs; returns (module, settings, httpx_calls)."""
    calls: list[dict] = []
    httpx = types.ModuleType("httpx")
    httpx.next_response = _Resp({"ok": True})

    def post(url, **kw):
        calls.append({"url": url, **kw})
        return httpx.next_response

    httpx.post = post
    cfg = types.ModuleType("app.core.config")
    settings = _Settings()
    cfg.settings = settings
    for name, mod in (("httpx", httpx), ("app", types.ModuleType("app")), ("app.core", types.ModuleType("app.core")), ("app.core.config", cfg)):
        sys.modules[name] = mod
    spec = importlib.util.spec_from_file_location("email_service_under_test", ROOT / "app" / "services" / "email_service.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.RETRY_DELAYS = ()
    mod._httpx = httpx  # handy handle for the tests
    return mod, settings, calls


def test_provider_name_is_cleaned():
    es, s, _ = _load()
    for raw in ("webhook", "Webhook", " webhook ", "webhook\n", '"webhook"', "'WEBHOOK' "):
        s.EMAIL_PROVIDER = raw
        assert es.provider_name() == "webhook", raw
    s.EMAIL_PROVIDER = None
    assert es.provider_name() == "console"


def test_is_live_needs_real_credentials():
    es, s, _ = _load()
    assert not es.is_live()  # console
    s.EMAIL_PROVIDER = "webhook"
    assert not es.is_live()
    s.EMAIL_WEBHOOK_URL, s.EMAIL_WEBHOOK_SECRET = "https://script.google.com/x/exec", "  "
    assert not es.is_live()  # blank secret
    s.EMAIL_WEBHOOK_SECRET = "abc"
    assert es.is_live()
    s.EMAIL_PROVIDER = "resend"
    assert not es.is_live()
    s.RESEND_API_KEY = "re_123"
    assert es.is_live()
    s.EMAIL_PROVIDER = "smtp"
    assert not es.is_live()
    s.SMTP_HOST = "smtp.gmail.com"
    assert es.is_live()


def test_console_is_dev_success_but_typos_and_missing_config_fail():
    es, s, _ = _load()
    assert es.try_send("a@b.co", "s", "t") == (True, None)  # console: dev mode prints the message
    s.EMAIL_PROVIDER = "webook"  # typo must NOT behave like console
    ok, err = es.try_send("a@b.co", "s", "t")
    assert ok is False and "Unknown EMAIL_PROVIDER" in err
    for prov in ("webhook", "smtp", "resend"):
        s.EMAIL_PROVIDER = prov
        ok, err = es.try_send("a@b.co", "s", "t")
        assert ok is False and prov.upper()[:4] in err.upper(), (prov, err)


def test_webhook_success_sends_cleaned_url_and_secret():
    es, s, calls = _load()
    s.EMAIL_PROVIDER = " webhook "
    s.EMAIL_WEBHOOK_URL = "  https://script.google.com/macros/s/AKfy/exec \n"
    s.EMAIL_WEBHOOK_SECRET = " topsecret\n"
    es._httpx.next_response = _Resp({"ok": True, "remaining": 42})
    assert es.send_password_reset_code("p@q.com", "123456") is True
    c = calls[-1]
    assert c["url"] == "https://script.google.com/macros/s/AKfy/exec"
    assert c["json"]["secret"] == "topsecret" and c["json"]["to"] == "p@q.com"
    assert "123456" in c["json"]["subject"] and "123456" in c["json"]["text"] and "123456" in c["json"]["html"]
    assert c["follow_redirects"] is True


def test_webhook_failures_are_reported_with_helpful_text():
    es, s, _ = _load()
    s.EMAIL_PROVIDER = "webhook"
    s.EMAIL_WEBHOOK_URL, s.EMAIL_WEBHOOK_SECRET = "https://x/exec", "k"

    es._httpx.next_response = _Resp({"ok": False, "error": "forbidden"})
    ok, err = es.try_send("a@b.co", "s", "t")
    assert ok is False and "EMAIL_WEBHOOK_SECRET" in err

    es._httpx.next_response = _Resp({"ok": False, "error": "quota", "remaining": 0})
    ok, err = es.try_send("a@b.co", "s", "t")
    assert ok is False and "daily" in err

    es._httpx.next_response = _Resp(json_error=True)  # Google sign-in page instead of JSON
    ok, err = es.try_send("a@b.co", "s", "t")
    assert ok is False and "/exec" in err and "Anyone" in err

    es._httpx.next_response = _Resp(status_error="500 server error")
    ok, err = es.try_send("a@b.co", "s", "t")
    assert ok is False and "500" in err

    assert es.send_email("a@b.co", "s", "t") is False  # the bool wrapper agrees


def test_send_with_retry_behaviour():
    es, _, _ = _load()
    es.RETRY_DELAYS = (0, 0)  # 3 attempts, no waiting

    seq = iter([False, False, True])
    n = {"calls": 0}

    def flaky():
        n["calls"] += 1
        return next(seq)

    assert es.send_with_retry(flaky, "t") is True and n["calls"] == 3

    n["calls"] = 0

    def never():
        n["calls"] += 1
        return False

    assert es.send_with_retry(never, "t") is False and n["calls"] == 3

    assert es.send_with_retry(lambda: None, "t") is True  # only an explicit False is a failure

    n["calls"] = 0

    def boom():
        n["calls"] += 1
        raise RuntimeError("provider exploded")

    assert es.send_with_retry(boom, "t") is False and n["calls"] == 3  # exceptions are failed attempts, not crashes

    es.RETRY_DELAYS = ()
    n["calls"] = 0
    assert es.send_with_retry(never, "t") is False and n["calls"] == 1


def test_email_templates_contain_the_code_and_footer():
    es, s, _ = _load()
    seen = {}

    def capture(to, subject, text, html=None):
        seen.update(to=to, subject=subject, text=text, html=html)
        return True

    es.send_email = capture
    assert es.send_password_reset_code("p@q.com", "004217") is True
    assert seen["subject"].startswith("004217") and "004217" in seen["text"] and "004217" in seen["html"]
    assert "15 minutes" in seen["text"] and "no-reply" in seen["text"].lower()


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failed else 0)
