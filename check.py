#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checker import apple, decide, notify, parse
from checker import state as state_mod
from checker.errors import CheckerError, NotifyError

ROOT = Path(__file__).resolve().parent
TITLE_FAILING = "iPhone stock checker is failing"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Check Apple pickup stock and alert via ntfy")
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
    for section in ("product", "search", "alerts", "ntfy"):
        if section not in config:
            raise SystemExit("config.json is missing section %r" % section)
    return config


def format_alerts(alerts, label):
    title = "%s in stock" % label
    lines = []
    for alert in alerts:
        quote = alert.store.quote or "available"
        lines.append("- %s (%.1f mi): %s" % (alert.store.name, alert.store.distance_miles, quote))
    message = "\n".join(lines) + "\n\nTap to open Apple and order."
    return title, message


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
            try:
                notify.send(
                    settings["server"],
                    settings["topic"],
                    TITLE_FAILING,
                    "%d consecutive failures.\nLast error: %s" % (failures, exc),
                    priority=4,
                    tags=["warning"],
                    token=settings["token"],
                )
                state["failure_alerted_at"] = now.isoformat(timespec="seconds")
                print("failure notification sent")
            except NotifyError as notify_exc:
                print("failure notification failed: %s" % notify_exc, file=sys.stderr)

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

    settings = {
        "server": config["ntfy"].get("server") or "https://ntfy.sh",
        "topic": os.environ.get("NTFY_TOPIC") or config["ntfy"].get("topic"),
        "token": os.environ.get("NTFY_TOKEN") or None,
        "priority": int(config["ntfy"].get("priority", 5)),
        "tags": config["ntfy"].get("tags") or None,
        "threshold": int(config["alerts"]["failure_threshold"]),
    }

    if args.test:
        if args.dry_run:
            print("would send a test notification to %s" % settings["server"])
            return 0
        try:
            notify.send(
                settings["server"],
                settings["topic"],
                "iPhone stock checker test",
                "Notifications are working.",
                click=product_url,
                priority=settings["priority"],
                tags=settings["tags"],
                token=settings["token"],
            )
        except NotifyError as exc:
            print("test notification failed: %s" % exc, file=sys.stderr)
            return 1
        print("test notification sent")
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
        if args.dry_run:
            print("[dry-run] would send %r to ntfy:\n%s" % (title, message), file=human)
        else:
            try:
                notify.send(
                    settings["server"],
                    settings["topic"],
                    title,
                    message,
                    click=product_url,
                    priority=settings["priority"],
                    tags=settings["tags"],
                    token=settings["token"],
                )
            except NotifyError as exc:
                print("notification failed: %s" % exc, file=sys.stderr)
                return 1
            print(
                "notification sent for %d store(s): %s"
                % (len(alerts), ", ".join(alert.store.name for alert in alerts)),
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
