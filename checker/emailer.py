import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

from .errors import NotifyError

USER_AGENT = "ipchecker/1.0"
DEFAULT_FROM = "iPhone Stock Checker <onboarding@resend.dev>"
RESEND_ENDPOINT = "https://api.resend.com/emails"


def build_email_message(sender, recipient, subject, text, html_body=None):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


def build_resend_payload(sender, recipient, subject, text, html_body=None):
    payload = {"from": sender, "to": [recipient], "subject": subject, "text": text}
    if html_body:
        payload["html"] = html_body
    return payload


def send_email(settings, subject, text, html_body=None, timeout=20):
    recipient = (settings.get("to") or "").strip()
    if not recipient:
        raise NotifyError("ALERT_EMAIL is not set")
    sender = settings.get("from") or DEFAULT_FROM
    provider = (settings.get("provider") or "resend").lower()

    if provider == "resend":
        _send_resend(settings, sender, recipient, subject, text, html_body, timeout)
    elif provider == "smtp":
        _send_smtp(settings, sender, recipient, subject, text, html_body, timeout)
    else:
        raise NotifyError("unsupported email provider %r" % provider)


def _send_resend(settings, sender, recipient, subject, text, html_body, timeout):
    api_key = settings.get("api_key")
    if not api_key:
        raise NotifyError("RESEND_API_KEY is not set")

    payload = build_resend_payload(sender, recipient, subject, text, html_body)
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            if response.status >= 300:
                raise NotifyError("Resend returned HTTP %d" % response.status)
    except urllib.error.HTTPError as exc:
        detail = _resend_error_detail(exc)
        suffix = ": %s" % detail if detail else ""
        raise NotifyError("Resend returned HTTP %d%s" % (exc.code, suffix)) from exc
    except urllib.error.URLError as exc:
        raise NotifyError("Resend request failed: %s" % exc.reason) from exc


def _resend_error_detail(exc):
    try:
        data = json.loads(exc.read().decode("utf-8", "replace"))
    except (ValueError, OSError):
        return ""
    if not isinstance(data, dict):
        return ""
    return data.get("message") or data.get("name") or ""


def _send_smtp(settings, sender, recipient, subject, text, html_body, timeout):
    host = settings.get("smtp_host")
    port = int(settings.get("smtp_port") or 465)
    username = settings.get("smtp_username")
    password = settings.get("smtp_password")
    if not host:
        raise NotifyError("SMTP_HOST is not set")
    if not username or not password:
        raise NotifyError("SMTP_USERNAME and SMTP_PASSWORD are not set")

    message = build_email_message(sender, recipient, subject, text, html_body)
    security = (settings.get("smtp_security") or ("ssl" if port == 465 else "starttls")).lower()
    context = ssl.create_default_context()

    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(username, password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError("SMTP send failed: %s" % exc) from exc
