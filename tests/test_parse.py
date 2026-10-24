import json
import unittest
from pathlib import Path

from checker.errors import ParseError
from checker.parse import parse_pickup

FIXTURES = Path(__file__).parent / "fixtures"
PART = "MK1H4LL/A"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ParsePickupTest(unittest.TestCase):
    def test_unavailable_fixture(self):
        snapshot = parse_pickup(load("unavailable.json"), PART)
        self.assertEqual(len(snapshot.stores), 3)
        self.assertFalse(any(store.available for store in snapshot.stores))
        self.assertEqual(snapshot.unknown, {"R582": "mystery"})

        pheasant = next(store for store in snapshot.stores if store.number == "R354")
        self.assertEqual(pheasant.name, "Pheasant Lane")
        self.assertAlmostEqual(pheasant.distance_miles, 2.23)
        self.assertIn("Check back", pheasant.quote)

    def test_available_fixture(self):
        snapshot = parse_pickup(load("available.json"), PART)
        available = {store.number for store in snapshot.stores if store.available}
        self.assertEqual(available, {"R354", "R095", "R032"})

        pheasant = next(store for store in snapshot.stores if store.number == "R354")
        self.assertEqual(pheasant.quote, "Available today at Apple Pheasant Lane")
        self.assertEqual(snapshot.unknown, {"R582": "mystery"})

    def test_missing_part_number(self):
        with self.assertRaises(ParseError):
            parse_pickup(load("unavailable.json"), "MK000LL/A")

    def test_missing_body(self):
        with self.assertRaises(ParseError):
            parse_pickup({}, PART)

    def test_unknown_only_is_an_error(self):
        payload = {
            "body": {
                "stores": [
                    {
                        "storeNumber": "R582",
                        "storeName": "Burlington",
                        "partsAvailability": {
                            PART: {"pickupDisplay": "mystery"}
                        },
                    }
                ]
            }
        }
        with self.assertRaises(ParseError):
            parse_pickup(payload, PART)

    def test_ineligible_overrides_enabled_flag(self):
        payload = {
            "body": {
                "stores": [
                    {
                        "storeNumber": "R354",
                        "storeName": "Pheasant Lane",
                        "storedistance": 2.23,
                        "partsAvailability": {
                            PART: {
                                "pickupDisplay": "ineligible",
                                "messageTypes": {"regular": {"storeSelectionEnabled": True}},
                            }
                        },
                    }
                ]
            }
        }
        snapshot = parse_pickup(payload, PART)
        self.assertFalse(snapshot.stores[0].available)

    def test_distance_falls_back_to_text(self):
        payload = {
            "body": {
                "stores": [
                    {
                        "storeNumber": "R354",
                        "storeName": "Pheasant Lane",
                        "storeDistanceWithUnit": "2.23 mi",
                        "partsAvailability": {
                            PART: {
                                "pickupDisplay": "default",
                                "messageTypes": {"regular": {"storeSelectionEnabled": False}},
                            }
                        },
                    }
                ]
            }
        }
        snapshot = parse_pickup(payload, PART)
        self.assertAlmostEqual(snapshot.stores[0].distance_miles, 2.23)


if __name__ == "__main__":
    unittest.main()
