#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checker import apple, decide, emailer, notify, parse
from checker import state as state_mod
from checker.errors import CheckerError, NotifyError

ROOT = Path(__file__).resolve().parent
TITLE_FAILING = "iPhone stock checker is failing"
TITLE_TEST = "iPhone stock checker test"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check Apple pickup stock and alert via ntfy and email"
    )
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--state", default=str(ROOT / "state.json"))
    parser.add_argument("--location", default=None, help="ZIP code (overrides config)")
    parser.add_argument("--dry-run", action="store_true", help="Do not notify or save state")
    parser.add_argument("--force", action="store_true", help="Alert even if already alerted")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument("--test", action="store_true", help="Send a test notification and exit")
    return parser.parse_args(argv)


def load_config(path):
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    for section in ("product", "search", "alerts", "ntfy", "email"):
        if section not in config:
            raise SystemExit("config.json is missing section %r" % section)
    return config


def build_settings(config):
    ntfy_config = config["ntfy"]
    email_config = config["email"]
    return {
        "threshold": int(config["alerts"]["failure_threshold"]),
        "ntfy": {
            "enabled": bool(ntfy_config.get("enabled", True)),
            "server": ntfy_config.get("server") or "https://ntfy.sh",
            "topic": os.environ.get("NTFY_TOPIC") or ntfy_config.get("topic") or "",
            "token": os.environ.get("NTFY_TOKEN") or None,
            "priority": int(ntfy_config.get("priority", 5)),
            "tags": ntfy_config.get("tags") or None,
        },
        "email": {
            "enabled": bool(email_config.get("enabled", False)),
            "provider": (email_config.get("provider") or "resend").lower(),
            "from": os.environ.get("EMAIL_FROM") or email_config.get("from") or "",
            "to": os.environ.get("ALERT_EMAIL") or email_config.get("to") or "",
            "api_key": os.environ.get("RESEND_API_KEY") or "",
            "smtp_host": os.environ.get("SMTP_HOST") or email_config.get("smtp_host") or "",
            "smtp_port": int(
                os.environ.get("SMTP_PORT") or email_config.get("smtp_port") or 465
            ),
            "smtp_security": (
                os.environ.get("SMTP_SECURITY")
                or email_config.get("smtp_security")
                or ""
            ).lower(),
            "smtp_username": os.environ.get("SMTP_USERNAME") or "",
            "smtp_password": os.environ.get("SMTP_PASSWORD") or "",
        },
    }


def alert_lines(alerts):
    lines = []
    for alert in alerts:
        quote = alert.store.quote or "available"
        lines.append(
            "- %s (%.1f mi): %s"
            % (alert.store.name, alert.store.distance_miles, quote)
        )
    return lines


def format_alerts(alerts, label):
    title = "%s in stock" % label
    message = "\n".join(alert_lines(alerts)) + "\n\nTap to open Apple and order."
    return title, message


def format_email_html(alerts, label, product_url):
    items = "".join(
        "<li><strong>%s</strong> (%.1f mi) &mdash; %s</li>"
        % (
            html_mod.escape(alert.store.name),
            alert.store.distance_miles,
            html_mod.escape(alert.store.quote or "available"),
        )
        for alert in alerts
    )
    return (
        '<html><body style="font-family:-apple-system,Helvetica,Arial,sans-serif;'
        'font-size:16px;color:#111;">'
        "<p><strong>%s</strong> is available for pickup:</p>"
        "<ul>%s</ul>"
        '<p><a href="%s" style="display:inline-block;padding:12px 20px;'
        "background:#0071e3;color:#ffffff;text-decoration:none;border-radius:8px;"
        '">Buy now</a></p>'
        "</body></html>"
    ) % (html_mod.escape(label), items, html_mod.escape(product_url, quote=True))


def format_test_html(product_url):
    return (
        '<html><body style="font-family:-apple-system,Helvetica,Arial,sans-serif;'
        'font-size:16px;color:#111;">'
        "<p>Notifications are working.</p>"
        '<p><a href="%s" style="display:inline-block;padding:12px 20px;'
        "background:#0071e3;color:#ffffff;text-decoration:none;border-radius:8px;"
        '">Open Apple</a></p>'
        "</body></html>"
    ) % html_mod.escape(product_url, quote=True)


def enabled_channels(settings):
    names = []
    if settings["ntfy"]["enabled"]:
        names.append("ntfy")
    if settings["email"]["enabled"]:
        names.append("email")
    return names


def send_channels(settings, title, message, click=None, email_body=None, html_body=None):
    results = []

    ntfy_settings = settings["ntfy"]
    if ntfy_settings["enabled"]:
        try:
            notify.send(
                ntfy_settings["server"],
                ntfy_settings["topic"],
                title,
                message,
                click=click,
                priority=ntfy_settings["priority"],
                tags=ntfy_settings["tags"],
                token=ntfy_settings["token"],
            )
            results.append(("ntfy", None))
        except NotifyError as exc:
            results.append(("ntfy", exc))

    email_settings = settings["email"]
    if email_settings["enabled"]:
        try:
            emailer.send_email(
                email_settings,
                title,
                email_body if email_body is not None else message,
                html_body=html_body,
            )
            results.append(("email", None))
        except NotifyError as exc:
            results.append(("email", exc))

    return results


def delivered_channels(results):
    return [name for name, error in results if error is None]


def print_channel_failures(results):
    for name, error in results:
        if error is not None:
            print("%s notification failed: %s" % (name, error), file=sys.stderr)


def ping_healthcheck(url):
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as exc:
        print("healthcheck ping failed: %s" % exc, file=sys.stderr)


def should_send_failure(state, now):
    last = state.get("failure_alerted_at")
    if not last:
        return True
    try:
        parsed = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return now - parsed >= timedelta(hours=24)


def handle_failure(exc, state, args, settings):
    failures = int(state.get("failures", 0)) + 1
    state["failures"] = failures
    print("check failed (%d consecutive): %s" % (failures, exc), file=sys.stderr)

    now = datetime.now(timezone.utc)
    if failures >= settings["threshold"] and not args.dry_run:
        if should_send_failure(state, now):
            message = "%d consecutive failures.\nLast error: %s" % (failures, exc)
            results = send_channels(settings, TITLE_FAILING, message)
            print_channel_failures(results)
            delivered = delivered_channels(results)
            if delivered:
                state["failure_alerted_at"] = now.isoformat(timespec="seconds")
                print("failure notification sent via %s" % ", ".join(delivered))
            elif not results:
                print("failure notification skipped: no channels enabled", file=sys.stderr)

    if not args.dry_run:
        state_mod.save(args.state, state)
    return 0


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)

    part = config["product"]["part_number"]
    label = config["product"]["label"]
    product_url = config["product"]["url"]
    location = args.location or os.environ.get("APPLE_LOCATION") or config["search"]["location"]
    radius = float(config["search"]["radius_miles"])
    cooldown = float(config["alerts"]["cooldown_hours"])
    settings = build_settings(config)

    if args.test:
        channels = enabled_channels(settings)
        if args.dry_run:
            print("would send a test notification via %s" % (", ".join(channels) or "no channels"))
            return 0
        message = "Notifications are working."
        results = send_channels(
            settings,
            TITLE_TEST,
            message,
            click=product_url,
            email_body=message + "\n\nBuy now: " + product_url,
            html_body=format_test_html(product_url),
        )
        print_channel_failures(results)
        delivered = delivered_channels(results)
        failed = [name for name, error in results if error is not None]
        if not delivered:
            print("test notification failed on all channels", file=sys.stderr)
            return 1
        print("test notification sent via %s" % ", ".join(delivered))
        if failed:
            print("test failed on: %s" % ", ".join(failed), file=sys.stderr)
            return 1
        return 0

    state = state_mod.load(args.state)

    try:
        payload = apple.fetch_pickup([part], location)
        snapshot = parse.parse_pickup(payload, part)
    except CheckerError as exc:
        return handle_failure(exc, state, args, settings)

    human = sys.stderr if args.json else sys.stdout
    in_radius = [store for store in snapshot.stores if store.distance_miles <= radius]
    available = [store for store in in_radius if store.available]
    print(
        "%s @ %s: %d stores returned, %d within %.1f mi, %d available"
        % (part, location, len(snapshot.stores), len(in_radius), radius, len(available)),
        file=human,
    )
    if snapshot.unknown:
        print("unrecognized availability values: %s" % snapshot.unknown, file=sys.stderr)

    alerts, new_state = decide.evaluate(
        snapshot,
        state,
        radius_miles=radius,
        cooldown_hours=cooldown,
        force=args.force,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "part": part,
                    "location": location,
                    "stores": len(snapshot.stores),
                    "within_radius": len(in_radius),
                    "available": [
                        {
                            "store": store.number,
                            "name": store.name,
                            "distance_miles": store.distance_miles,
                            "quote": store.quote,
                        }
                        for store in available
                    ],
                    "alerts": [
                        {"store": alert.store.number, "reason": alert.reason}
                        for alert in alerts
                    ],
                    "unknown": snapshot.unknown,
                },
                indent=2,
                sort_keys=True,
            )
        )

    if alerts:
        title, message = format_alerts(alerts, label)
        email_body = "\n".join(alert_lines(alerts)) + "\n\nBuy now: " + product_url
        html_body = format_email_html(alerts, label, product_url)
        if args.dry_run:
            channels = ", ".join(enabled_channels(settings)) or "no channels"
            print(
                "[dry-run] would send %r via %s:\n%s" % (title, channels, message),
                file=human,
            )
        else:
            results = send_channels(
                settings,
                title,
                message,
                click=product_url,
                email_body=email_body,
                html_body=html_body,
            )
            print_channel_failures(results)
            delivered = delivered_channels(results)
            if not delivered:
                print("all notification channels failed", file=sys.stderr)
                return 1
            print(
                "notification sent via %s for %d store(s): %s"
                % (
                    ", ".join(delivered),
                    len(alerts),
                    ", ".join(alert.store.name for alert in alerts),
                ),
                file=human,
            )
    elif not args.json:
        print("no new availability")

    if args.dry_run:
        return 0

    state_mod.save(args.state, new_state)
    ping_healthcheck(os.environ.get("HEALTHCHECK_URL"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
