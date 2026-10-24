import os
import unittest
from unittest import mock

import check
from checker.decide import Alert
from checker.errors import NotifyError
from checker.parse import Store

CONFIG = {
    "alerts": {"failure_threshold": 3},
    "ntfy": {
        "enabled": True,
        "server": "https://ntfy.sh",
        "topic": "",
        "priority": 5,
        "tags": ["iphone"],
    },
    "email": {
        "enabled": True,
        "provider": "resend",
        "from": "from@example.com",
        "to": "",
        "smtp_port": 465,
        "smtp_security": "ssl",
    },
}


def settings():
    return {
        "threshold": 3,
        "ntfy": {
            "enabled": True,
            "server": "https://ntfy.sh",
            "topic": "test-topic",
            "token": None,
            "priority": 5,
            "tags": ["iphone"],
        },
        "email": {
            "enabled": True,
            "provider": "resend",
            "from": "from@example.com",
            "to": "to@example.com",
            "api_key": "key",
        },
    }


class BuildSettingsTest(unittest.TestCase):
    def test_env_overrides(self):
        env = {
            "NTFY_TOPIC": "env-topic",
            "ALERT_EMAIL": "env@example.com",
            "RESEND_API_KEY": "env-key",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            result = check.build_settings(CONFIG)
        self.assertEqual(result["ntfy"]["topic"], "env-topic")
        self.assertEqual(result["email"]["to"], "env@example.com")
        self.assertEqual(result["email"]["api_key"], "env-key")

    def test_disabled_channels(self):
        config = {
            "alerts": {"failure_threshold": 3},
            "ntfy": {"enabled": False},
            "email": {"enabled": False},
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            result = check.build_settings(config)
        self.assertEqual(check.enabled_channels(result), [])


class SendChannelsTest(unittest.TestCase):
    def test_both_delivered(self):
        with mock.patch("check.notify.send") as ntfy, mock.patch(
            "check.emailer.send_email"
        ) as email:
            results = check.send_channels(settings(), "Subject", "Message")
        self.assertEqual(check.delivered_channels(results), ["ntfy", "email"])
        ntfy.assert_called_once()
        email.assert_called_once()

    def test_partial_failure_keeps_success(self):
        with mock.patch(
            "check.notify.send", side_effect=NotifyError("ntfy down")
        ), mock.patch("check.emailer.send_email"):
            results = check.send_channels(settings(), "Subject", "Message")
        self.assertEqual(check.delivered_channels(results), ["email"])
        errors = {name: str(error) for name, error in results if error is not None}
        self.assertEqual(errors, {"ntfy": "ntfy down"})

    def test_all_channels_fail(self):
        with mock.patch(
            "check.notify.send", side_effect=NotifyError("ntfy down")
        ), mock.patch(
            "check.emailer.send_email", side_effect=NotifyError("email down")
        ):
            results = check.send_channels(settings(), "Subject", "Message")
        self.assertEqual(check.delivered_channels(results), [])

    def test_disabled_email_is_skipped(self):
        current = settings()
        current["email"]["enabled"] = False
        with mock.patch("check.notify.send"), mock.patch(
            "check.emailer.send_email"
        ) as email:
            results = check.send_channels(current, "Subject", "Message")
        self.assertEqual(check.delivered_channels(results), ["ntfy"])
        email.assert_not_called()

    def test_email_body_and_html_are_passed(self):
        with mock.patch("check.notify.send"), mock.patch(
            "check.emailer.send_email"
        ) as email:
            check.send_channels(
                settings(),
                "Subject",
                "Push message",
                email_body="Email message",
                html_body="<p>Email</p>",
            )
        email.assert_called_once()
        args, kwargs = email.call_args
        self.assertEqual(args[1], "Subject")
        self.assertEqual(args[2], "Email message")
        self.assertEqual(kwargs["html_body"], "<p>Email</p>")


class FormatEmailHtmlTest(unittest.TestCase):
    def test_escapes_store_and_product_text(self):
        store = Store(
            number="R1",
            name="A & B <Store>",
            distance_miles=2.25,
            available=True,
            quote='Tom & "Jerry"',
            display="available",
        )
        result = check.format_email_html(
            [Alert(store, "new")], "Phone <X>", "https://example.com/?a=1&b=2"
        )
        self.assertIn("A &amp; B &lt;Store&gt;", result)
        self.assertIn("Tom &amp; &quot;Jerry&quot;", result)
        self.assertIn("Phone &lt;X&gt;", result)
        self.assertIn("a=1&amp;b=2", result)


if __name__ == "__main__":
    unittest.main()
