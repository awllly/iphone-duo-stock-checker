import re
from dataclasses import dataclass, field
from typing import Dict, List

from .errors import ParseError

KNOWN_DISPLAYS = {"available", "default", "unavailable", "ineligible"}
DISTANCE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")


@dataclass(frozen=True)
class Store:
    number: str
    name: str
    distance_miles: float
    available: bool
    quote: str
    display: str


@dataclass
class Snapshot:
    stores: List[Store] = field(default_factory=list)
    unknown: Dict[str, str] = field(default_factory=dict)


def _distance(raw):
    value = raw.get("storedistance")
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    text = str(raw.get("storeDistanceWithUnit") or "")
    match = DISTANCE_RE.search(text)
    if match:
        return float(match.group(1))
    return float("inf")


def parse_pickup(payload, part_number):
    if not isinstance(payload, dict):
        raise ParseError("response is not an object")
    body = payload.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("stores"), list):
        raise ParseError("response missing body.stores")

    snapshot = Snapshot()
    for raw in body["stores"]:
        if not isinstance(raw, dict):
            continue
        number = raw.get("storeNumber")
        if not number:
            continue
        availability = (raw.get("partsAvailability") or {}).get(part_number)
        if not isinstance(availability, dict):
            continue

        display = str(availability.get("pickupDisplay") or "")
        regular = (availability.get("messageTypes") or {}).get("regular") or {}
        enabled = regular.get("storeSelectionEnabled")
        quote = (
            regular.get("storePickupQuote")
            or availability.get("pickupSearchQuote")
            or ""
        )

        if display in KNOWN_DISPLAYS or isinstance(enabled, bool):
            if display == "available":
                available = True
            elif display in ("unavailable", "ineligible"):
                available = False
            else:
                available = enabled is True
            snapshot.stores.append(
                Store(
                    number=str(number),
                    name=str(raw.get("storeName") or number),
                    distance_miles=_distance(raw),
                    available=available,
                    quote=str(quote),
                    display=display,
                )
            )
        else:
            snapshot.unknown[str(number)] = display or "<empty>"

    if not snapshot.stores:
        if snapshot.unknown:
            raise ParseError(
                "unrecognized pickupDisplay values: %s" % snapshot.unknown
            )
        raise ParseError("no availability entries for part %s" % part_number)
    return snapshot
