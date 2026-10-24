import unittest

from checker import emailer
from checker.errors import NotifyError


class BuildEmailMessageTest(unittest.TestCase):
    def test_plain_message(self):
        message = emailer.build_email_message(
            "from@example.com", "to@example.com", "Test subject", "Test body"
        )
        self.assertEqual(message["Subject"], "Test subject")
        self.assertEqual(message["From"], "from@example.com")
        self.assertEqual(message["To"], "to@example.com")
        self.assertFalse(message.is_multipart())
        self.assertEqual(message.get_content().strip(), "Test body")

    def test_html_alternative(self):
        message = emailer.build_email_message(
            "from@example.com",
            "to@example.com",
            "Test subject",
            "Test body",
            "<p>Test body</p>",
        )
        self.assertTrue(message.is_multipart())
        parts = list(message.iter_parts())
        self.assertEqual(
            [part.get_content_type() for part in parts], ["text/plain", "text/html"]
        )
        self.assertIn("<p>Test body</p>", parts[1].get_content())


class BuildResendPayloadTest(unittest.TestCase):
    def test_plain_payload(self):
        payload = emailer.build_resend_payload(
            "from@example.com", "to@example.com", "Subject", "Body"
        )
        self.assertEqual(payload["from"], "from@example.com")
        self.assertEqual(payload["to"], ["to@example.com"])
        self.assertEqual(payload["subject"], "Subject")
        self.assertEqual(payload["text"], "Body")
        self.assertNotIn("html", payload)

    def test_html_payload(self):
        payload = emailer.build_resend_payload(
            "from@example.com", "to@example.com", "Subject", "Body", "<p>Body</p>"
        )
        self.assertEqual(payload["html"], "<p>Body</p>")


class SendEmailValidationTest(unittest.TestCase):
    def test_missing_recipient(self):
        with self.assertRaisesRegex(NotifyError, "ALERT_EMAIL"):
            emailer.send_email({"provider": "resend", "to": ""}, "Subject", "Body")

    def test_missing_resend_key(self):
        with self.assertRaisesRegex(NotifyError, "RESEND_API_KEY"):
            emailer.send_email(
                {
                    "provider": "resend",
                    "to": "to@example.com",
                    "from": "from@example.com",
                    "api_key": "",
                },
                "Subject",
                "Body",
            )

    def test_missing_smtp_host(self):
        with self.assertRaisesRegex(NotifyError, "SMTP_HOST"):
            emailer.send_email(
                {
                    "provider": "smtp",
                    "to": "to@example.com",
                    "from": "from@example.com",
                    "smtp_host": "",
                    "smtp_username": "user",
                    "smtp_password": "pass",
                },
                "Subject",
                "Body",
            )

    def test_unsupported_provider(self):
        with self.assertRaisesRegex(NotifyError, "unsupported"):
            emailer.send_email(
                {"provider": "pigeon", "to": "to@example.com"}, "Subject", "Body"
            )


if __name__ == "__main__":
    unittest.main()
