from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from .parse import Snapshot, Store


@dataclass
class Alert:
    store: Store
    reason: str


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate(
    snapshot: Snapshot,
    state: Optional[dict],
    radius_miles: float,
    cooldown_hours: float,
    now: Optional[datetime] = None,
    force: bool = False,
) -> Tuple[List[Alert], dict]:
    now = now or datetime.now(timezone.utc)
    state = state or {}
    previous = state.get("pickup") or {}
    alerted = state.get("alerted") or {}
    cooldown = timedelta(hours=cooldown_hours)

    available = [
        store
        for store in snapshot.stores
        if store.available and store.distance_miles <= radius_miles
    ]

    alerts = []
    new_pickup = {}
    new_alerted = {}

    for store in available:
        new_pickup[store.number] = {
            "name": store.name,
            "distance_miles": round(store.distance_miles, 2),
            "quote": store.quote,
        }
        last_alert = _parse_timestamp(alerted.get(store.number))
        reason = None
        if force:
            reason = "forced"
        elif store.number not in previous:
            reason = "new"
        elif last_alert is None:
            reason = "new"
        elif now - last_alert >= cooldown:
            reason = "reminder"

        if reason:
            alerts.append(Alert(store=store, reason=reason))
            new_alerted[store.number] = now.isoformat(timespec="seconds")
        elif alerted.get(store.number):
            new_alerted[store.number] = alerted[store.number]

    new_state = dict(state)
    new_state["schema"] = 1
    new_state["pickup"] = new_pickup
    new_state["alerted"] = new_alerted
    new_state["failures"] = 0
    new_state.pop("failure_alerted_at", None)
    return alerts, new_state
