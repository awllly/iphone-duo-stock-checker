# iPhone Duo Stock Checker

Hourly Apple Store stock check for **iPhone Duo 512 GB Night Sky (unlocked)**, within **10 miles of ZIP 03060**, with push alerts to an iPhone via [ntfy](https://ntfy.sh) and email via [Resend](https://resend.com). Runs entirely on the GitHub Actions and Resend free tiers. No servers, no database, no dependencies.

## What it watches

| Setting | Value |
|---|---|
| Product | iPhone Duo, 512 GB, Night Sky, unlocked |
| Part number | `MK1H4LL/A` |
| Location | 03060 |
| Radius | 10 miles |
| Signal | In-store pickup availability |
| Schedule | Hourly at minute 17 |
| Alert channels | ntfy (push) + Resend (email) |

Online delivery is intentionally not monitored in v1. Apple's delivery endpoint currently returns HTTP 541, and delivery dates alone are too noisy to alert on.

## How it works

1. The workflow restores `state.json` from the `state` branch, if it exists.
2. `check.py` calls Apple's pickup endpoint:
   `https://www.apple.com/shop/retail/pickup-message?parts.0=MK1H4LL/A&location=03060`
3. The response is parsed into stores, distances, and availability.
4. A store triggers an alert when it becomes available, when a new store appears, or after a 6-hour reminder cooldown.
5. One batched ntfy notification and one email are sent, both linking to the buy page.
6. If `state.json` changed, it is force-pushed as a single commit to the `state` branch.

A failed or blocked check is treated as **unknown**, never as "out of stock." After 3 consecutive failures, it sends an "iPhone stock checker is failing" alert (at most once per 24 hours) through both channels.

Delivery is best-effort per channel: if at least one channel succeeds, the alert is recorded and will not repeat. Failed channels are logged. If both fail, state is not advanced and the next run retries.

## Setup

```sh
git init
git add .
git commit -m "iPhone Duo stock checker"
gh repo create iphone-duo-stock --public --source=. --push
```

Create a random topic and store it as a secret:

```sh
gh secret set NTFY_TOPIC --body "$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
```

Subscribe to the same topic in the ntfy iOS app. Treat the topic name as a password: on ntfy.sh, anyone who knows it can read your alerts.

### Email via Resend

Sign up at [resend.com](https://resend.com) using the address that should receive alerts, then create an API key with **Sending access**:

```sh
gh secret set ALERT_EMAIL --body "you@example.com"
gh secret set RESEND_API_KEY --body "<resend-api-key>"
```

Without a verified domain, Resend only allows `onboarding@resend.dev` as the sender and only delivers to the account email. That sender is the default in `config.json`. To deliver to a different address, verify a domain in Resend and override the sender:

```sh
gh secret set EMAIL_FROM --body "iPhone Stock Checker <alerts@your-domain>"
```

Verify end-to-end with a one-time test:

```sh
gh workflow run check.yml -f send_test=true
```

The test fails if either enabled channel fails, so a green run means both delivered.

SMTP is also supported: set `"provider": "smtp"` in `config.json`, add `SMTP_HOST`, `SMTP_PORT`, and `SMTP_SECURITY` as repository variables, and add `SMTP_USERNAME` and `SMTP_PASSWORD` as secrets. Port 465 uses implicit TLS; port 587 uses STARTTLS.

Optional configuration:

```sh
gh variable set APPLE_LOCATION --body "03060"
gh secret set HEALTHCHECK_URL --body "https://hc-ping.com/<uuid>"
gh secret set NTFY_TOKEN --body "<token>"
```

- `APPLE_LOCATION` overrides the ZIP in `config.json`.
- `HEALTHCHECK_URL` is pinged after every successful check. Point a free [Healthchecks.io](https://healthchecks.io) check at it and route its notifications to ntfy to detect a silently dead checker.
- `NTFY_TOKEN` is only needed for an authenticated or self-hosted ntfy server.

No action is needed to create the `state` branch; the first run creates it and stores only `state.json`.

## Running locally

Requires Python 3.9+ and nothing else.

```sh
python3 -m unittest discover -s tests -v
python3 check.py --dry-run
NTFY_TOPIC=<topic> ALERT_EMAIL=<address> RESEND_API_KEY=<key> python3 check.py --test
```

Useful flags:

| Flag | Effect |
|---|---|
| `--dry-run` | Fetch and report without notifying, saving state, or pinging Healthchecks |
| `--force` | Alert even if the store was already alerted |
| `--json` | Print machine-readable results to stdout |
| `--test` | Send a test notification to every configured channel and exit |
| `--location ZIP` | Override the configured ZIP |
| `--state PATH` | Use a different state file |
| `--config PATH` | Use a different config file |

## Configuration

`config.json`:

```json
{
  "product": {
    "part_number": "MK1H4LL/A",
    "label": "iPhone Duo 512GB Night Sky (unlocked)",
    "url": "https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-512gb-night-sky-unlocked"
  },
  "search": { "location": "03060", "radius_miles": 10.0 },
  "alerts": { "cooldown_hours": 6, "failure_threshold": 3 },
  "ntfy": {
    "enabled": true,
    "server": "https://ntfy.sh",
    "topic": "",
    "priority": 5,
    "tags": ["iphone", "rotating_light"]
  },
  "email": {
    "enabled": true,
    "provider": "resend",
    "from": "iPhone Stock Checker <onboarding@resend.dev>",
    "to": "",
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_security": ""
  }
}
```

`NTFY_TOPIC` takes precedence over `ntfy.topic`. `APPLE_LOCATION` takes precedence over `search.location`. `ALERT_EMAIL`, `EMAIL_FROM`, `RESEND_API_KEY`, and the `SMTP_*` variables override the email section. Set `"ntfy": {"enabled": false}` to use email only; set `"email": {"enabled": false}` to disable email. An empty `smtp_security` infers implicit TLS on port 465 and STARTTLS otherwise.

To watch a different model, update `part_number`, `label`, and `url`. Retrieve the part number from the product page's embedded JSON; the unlocked variant is the one ending in `LL/A` whose JSON-LD SKU includes `+unlocked`. This build supports one part number at a time.

## The state branch

`state.json` tracks current availability, alert timestamps, and consecutive failures:

```json
{
  "alerted": { "R354": "2026-10-24T17:17:03+00:00" },
  "failures": 0,
  "pickup": {
    "R354": { "distance_miles": 2.23, "name": "Pheasant Lane", "quote": "Available today" }
  },
  "schema": 1
}
```

The branch is force-pushed as a single orphan commit and only updated when the file's bytes change. Quiet hours produce no commits. Do not add branch protection that blocks force-pushes to `state`. Do not commit `state.json` to `main`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `check failed ... HTTP 541` | Apple blocked the request or the endpoint changed. The checker uses `/shop/retail/pickup-message`; do not switch to `/shop/fulfillment-messages`, which is blocked. |
| No notifications for days | Confirm `NTFY_TOPIC` matches the app subscription and run `python3 check.py --test`. |
| `NTFY_TOPIC is not set` | The secret is missing or the local env var is unset. |
| `RESEND_API_KEY is not set` | The Resend secret is missing. |
| `Resend returned HTTP 403 ... own email address` | Resend test mode only delivers to the account email. Sign up with that address or verify a domain. |
| `Resend returned HTTP 401` | The API key is invalid or lacks sending permission. |
| Email does not arrive | Check spam, confirm `ALERT_EMAIL`, and run `gh workflow run check.yml -f send_test=true`. |
| `all notification channels failed` | Both ntfy and email failed; state was not advanced. Check the per-channel errors. |
| State branch does not update | This is expected when nothing changed. Check the "state unchanged" log line. |
| Alerts repeat every 6 hours | That is the reminder cooldown in `alerts.cooldown_hours`. |
| Only one store is checked | Only Pheasant Lane is within 10 miles of 03060. Increase `radius_miles` to include more. |

## Limitations

- Detection latency is up to one hour.
- Availability does not guarantee the quantity you want at checkout.
- GitHub Actions runners use datacenter IPs; Apple may block them more aggressively than a home connection. If that happens, the fetch layer can be moved to a Cloudflare Worker or Raspberry Pi while keeping the parser and decision logic.
- The in-stock response shape has not yet been observed live; the parser is strict and will fail loudly on unrecognized values instead of guessing.
- The repo is public and `config.json` contains ZIP 03060. Move it to the `APPLE_LOCATION` variable if that matters.
- ntfy.sh topics are public to anyone who knows the name; the random name is the only secret.
- Email can land in spam. Resend test-mode mail is limited to the account address, and unverified-domain mail uses `onboarding@resend.dev`.

## Layout

```
check.py                       CLI and orchestration
config.json                    Product, location, alert settings
checker/apple.py               Apple pickup fetch and error handling
checker/parse.py               Response parsing
checker/decide.py              Alert and cooldown logic
checker/notify.py              ntfy publishing
checker/emailer.py             Resend and SMTP email delivery
checker/state.py               State persistence
tests/                         Unit tests and fixtures
.github/workflows/check.yml    Hourly workflow
session_memory.md              Detailed agent/developer handoff notes
```
