import unittest
from datetime import datetime, timedelta, timezone

from checker.decide import evaluate
from checker.parse import Snapshot, Store

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
RADIUS = 10.0
COOLDOWN = 6.0


def store(number, distance, available=True, name=None):
    return Store(
        number=number,
        name=name or number,
        distance_miles=distance,
        available=available,
        quote="Available today" if available else "Check back",
        display="available" if available else "default",
    )


def snapshot(*stores):
    return Snapshot(stores=list(stores))


def run(snap, state, now=NOW, force=False):
    return evaluate(
        snap,
        state,
        radius_miles=RADIUS,
        cooldown_hours=COOLDOWN,
        now=now,
        force=force,
    )


class EvaluateTest(unittest.TestCase):
    def test_first_run_alerts_only_inside_radius(self):
        alerts, state = run(
            snapshot(
                store("R354", 2.2),
                store("R095", 9.4),
                store("R032", 38.4),
                store("R999", 5.0, available=False),
            ),
            {},
        )
        self.assertEqual({alert.store.number for alert in alerts}, {"R354", "R095"})
        self.assertEqual(set(state["pickup"]), {"R354", "R095"})
        self.assertEqual(state["alerted"]["R354"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(state["failures"], 0)

    def test_second_run_is_quiet(self):
        _, state = run(snapshot(store("R354", 2.2)), {})
        alerts, state = run(snapshot(store("R354", 2.2)), state, now=NOW + timedelta(hours=1))
        self.assertEqual(alerts, [])
        self.assertEqual(set(state["pickup"]), {"R354"})

    def test_reminder_after_cooldown(self):
        _, state = run(snapshot(store("R354", 2.2)), {})
        alerts, _ = run(snapshot(store("R354", 2.2)), state, now=NOW + timedelta(hours=7))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].reason, "reminder")

    def test_new_store_triggers_alert(self):
        _, state = run(snapshot(store("R354", 2.2)), {})
        alerts, state = run(
            snapshot(store("R354", 2.2), store("R095", 9.4)),
            state,
            now=NOW + timedelta(hours=1),
        )
        self.assertEqual([alert.store.number for alert in alerts], ["R095"])
        self.assertEqual(alerts[0].reason, "new")

    def test_store_disappearing_then_returning_alerts_again(self):
        _, state = run(snapshot(store("R354", 2.2)), {})
        alerts, state = run(
            snapshot(store("R354", 2.2, available=False)),
            state,
            now=NOW + timedelta(hours=1),
        )
        self.assertEqual(alerts, [])
        self.assertEqual(state["pickup"], {})

        alerts, state = run(
            snapshot(store("R354", 2.2)),
            state,
            now=NOW + timedelta(hours=2),
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].reason, "new")

    def test_force_re_alerts(self):
        _, state = run(snapshot(store("R354", 2.2)), {})
        alerts, _ = run(snapshot(store("R354", 2.2)), state, now=NOW + timedelta(minutes=20), force=True)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].reason, "forced")

    def test_unknown_distance_is_ignored(self):
        alerts, state = run(snapshot(store("R000", float("inf"))), {})
        self.assertEqual(alerts, [])
        self.assertEqual(state["pickup"], {})


if __name__ == "__main__":
    unittest.main()
