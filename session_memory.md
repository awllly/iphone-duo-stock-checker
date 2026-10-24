# Session Memory — iPhone Duo Stock Checker

Last updated: 2026-10-24
Status: deployed to https://github.com/awllly/iphone-duo-stock-checker and verified end-to-end for ntfy. Email via Resend was added on 2026-10-24; `ALERT_EMAIL` is configured, but `RESEND_API_KEY` still needs to be added and the email path verified.

This file is the handoff context for a new AI agent or developer. Read it before changing anything.

## 1. What the user asked for

A free service that checks Apple stock for one specific iPhone and sends a push notification to their iPhone when it becomes available.

User requirements, as confirmed:

- Target: **iPhone Duo** (the 2026 foldable; "Duo" is the model name, not a quantity), **512 GB**, **Night Sky**, **unlocked / "Connect on your own later"**.
- Location: ZIP **03060** (Nashua, NH area). Search radius: **10 miles**.
- Wants both in-store pickup and online delivery awareness. **v1 is pickup only**; delivery was explicitly deferred.
- Hosting: **GitHub Actions**, free tier, **public repo** is acceptable.
- Alerts: **ntfy**, one iPhone, **plain secret topic** (no ntfy account/token required, though token support exists).
- Alerts: also **email via Resend** to **awly.code@gmail.com**, sent alongside ntfy. Both channels are kept. Failure alerts go to both. Delivery is best-effort per channel.
- Schedule: **once per hour**. Job execution should finish well under a minute (detection latency is up to one hour by design).
- State persistence: a dedicated **`state` branch** is fine.
- Just Apple. No Best Buy or carrier inventory.

## 2. Current status

Deployed and verified:

- GitHub repo: `awllly/iphone-duo-stock-checker`, public, default branch `main`.
- Local `main` is pushed and tracks `origin/main`.
- GitHub Actions run `40066248564` (push-triggered during setup) succeeded in 8 seconds on 2026-10-24T05:26Z from an Azure runner:
  `MK1H4LL/A @ 03060: 12 stores returned, 1 within 10.0 mi, 0 available`.
  This confirms Apple's endpoint works from GitHub's datacenter IP as of that date.
- The run created the `state` branch, which contains only `state.json`:
  `{"alerted": {}, "failures": 0, "pickup": {}, "schema": 1}`.
- A temporary `push` trigger was added for that verification run and then removed. The workflow is back to schedule + `workflow_dispatch` only.
- GitHub Actions run `40066573794` (`ntfy smoke test`) succeeded in 6 seconds. The log shows `NTFY_TOPIC: ***` and `test notification sent`, confirming the secret is wired correctly and ntfy accepted the push. A temporary `.github/workflows/ntfy-smoke.yml` was used and then removed.
- GitHub Actions run `40066718153` (manual `workflow_dispatch` by the user, `dry_run=false`) succeeded in 10 seconds: `12 stores returned, 1 within 10.0 mi, 0 available`; state unchanged.
- Run `40066981712` was a second temporary push-triggered real check; same result, then the push trigger was removed again.
- The `gh` CLI was re-authenticated via the device flow as `awllly` with a classic OAuth token (scopes `repo`, `workflow`). `gh workflow run` now works: dispatch run `40068724234` (`dry_run=false`) succeeded in 7 seconds with the same result, `0 available`.
- Dispatch run `40070346150` (after the email feature) succeeded in 8 seconds with the same result, confirming the new code and config load on the runner.
- Python 3.9-compatible, stdlib-only checker (`urllib`, `json`, `dataclasses`, `unittest`). No `requirements.txt`, no pip install step.
- Apple pickup fetcher with block detection and one retry.
- Parser with strict unknown-value handling.
- Alert decision logic: new store, 6-hour reminder cooldown, force mode.
- ntfy publisher with title, priority, tags, click URL, and a "Buy now" action.
- Resend email publisher with plain text and HTML (buy button), plus optional SMTP backend.
- Channel orchestration: ntfy and email are independent; at least one success is enough to record an alert.
- State load/save with stable key ordering.
- Hourly GitHub Actions workflow at minute 17, with manual dispatch (`dry_run`, `force`, `send_test`), concurrency guard, and orphan-commit state branch updates.
- 30 unit tests using fixtures.
- ntfy publish verified with HTTP 200 against a throwaway topic.
- State-branch orphan commit + force-push flow verified in production.
- Two consecutive live runs produced byte-identical `state.json` (no commit noise).

Outstanding:

- Confirm with the user that the test notification actually appeared on their iPhone.
- No real in-stock event has been observed, so the "available" fixture is synthetic.
- Delivery ETA is not implemented and has no known working endpoint.
- No Healthchecks.io check created yet (code supports `HEALTHCHECK_URL`).
- `RESEND_API_KEY` is not set yet. Until it is, email sends fail and are logged; ntfy still delivers and state still advances because delivery is best-effort.
- Email has not been verified end-to-end. Add the key, then dispatch `send_test=true`.
- No remaining tooling blocker: `gh` is authenticated with `repo` and `workflow` scopes, so dispatch, secret/variable management, and content pushes all work.

## 3. Verified external facts (2026-10-24)

These were confirmed with live read-only requests. Trust them, but re-verify if Apple changes its site.

- Product page: `https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-512gb-night-sky-unlocked`
- Unlocked 512 GB Night Sky part number: **`MK1H4LL/A`** (price $2,199).
  - The page lists 8 parts for Night Sky / Star White across AT&T, T-Mobile, Verizon, and unlocked. `MK1H4LL/A` is the unlocked Night Sky 512 GB.
- Working pickup endpoint:
  `GET https://www.apple.com/shop/retail/pickup-message?parts.0=MK1H4LL/A&location=03060`
- Response shape used:
  - `body.stores[]`
  - `storeNumber`, `storeName`, `storedistance` (miles), `storeDistanceWithUnit`
  - `partsAvailability["MK1H4LL/A"].pickupDisplay`
  - `.messageTypes.regular.storeSelectionEnabled`
  - `.messageTypes.regular.storePickupQuote`
- Observed unavailable state: `pickupDisplay: "default"`, `storeSelectionEnabled: false`, quote like `"Check back for availability on 10.24"`.
- Observed nearest store: Pheasant Lane (R354), Nashua NH, 2.23 mi.
- Only **1** store falls within 10 miles for ZIP 03060; the endpoint returned 12 stores total.
- **Critical trap:** `https://www.apple.com/shop/fulfillment-messages` returns **HTTP 541** (blocked). Most tutorials and older projects use it. Do not switch to it. It also backs the product page's `deliveryMessageUrl`, which is why delivery is not implemented.
- Apple rate-limits pickup queries per IP (community reports: roughly 30 queries before a temporary block of 10+ minutes). At one request per hour this is irrelevant.
- Response headers/UA used successfully: browser User-Agent, `Accept: application/json, text/javascript, */*; q=0.01`, `Referer` = product page.

## 4. Key design decisions and rationale

1. **Use `/shop/retail/pickup-message`, not `/shop/fulfillment-messages`.** The latter is blocked with 541.
2. **Failures are `unknown`, never "out of stock."** A checker that silently reports no stock forever is worse than one that complains. Blocked/parse failures increment `failures` and eventually alert.
3. **Hourly cron at `17 * * * *`.** The user asked for hourly. Minute 17 avoids GitHub's top-of-hour scheduler congestion.
4. **State on an orphan `state` branch, force-pushed as a single commit.** Avoids repo history noise and merge conflicts. The branch contains only `state.json`.
5. **Commit state only when bytes change.** `checked_at` is deliberately not stored, so quiet runs do not commit. `failures` and availability transitions are the only things that change.
6. **No dependencies.** Stdlib `urllib` keeps the job around 10–15 seconds and removes supply-chain and install-step risk. Python 3.9 compatibility matters because the user's Mac is on 3.9.6.
7. **Strict parsing.** Any `pickupDisplay` value outside the known set is recorded as unknown. If every store is unknown, the run fails loudly rather than guessing.
8. **Alert semantics.** Alert when a store becomes available, when a new store appears, or after a 6-hour cooldown while still available. A store that goes unavailable and returns alerts again.
9. **One batched notification per run**, not one per store, to stay well within ntfy.sh limits.
10. **v1 is pickup only.** Delivery alerts would fire constantly if based on "a date exists"; the eventual rule should be "ETA improves below a threshold."
11. **Dual channels, best-effort.** ntfy remains primary; Resend email is a backup. If one channel fails and the other succeeds, the alert is recorded and the failure is logged. If both fail, state is not saved, so the next hourly run retries. This avoids hourly ntfy spam when email is misconfigured.
12. **Resend over SMTP.** Resend's HTTPS API avoids outbound SMTP blocking on CI runners and needs no app password. SMTP remains implemented as an option.

## 5. Architecture and data flow

```
GitHub Actions (hourly, :17)
  -> restore state.json from origin/state (if present)
  -> python3 check.py
       -> checker.apple.fetch_pickup([MK1H4LL/A], location)
       -> checker.parse.parse_pickup(...)
       -> checker.decide.evaluate(snapshot, state, radius, cooldown)
       -> if alerts: checker.notify.send(...) AND checker.emailer.send_email(...)
       -> checker.state.save(...) if at least one channel succeeded
       -> ping HEALTHCHECK_URL on success
  -> compare state.json to previous bytes
  -> if changed: orphan commit state.json and force-push to `state`
```

Alert condition inside `decide.evaluate`:

- Store must be `available` and `distance_miles <= 10`.
- Alert if:
  - `force` is set, or
  - store was not in the previous `pickup` map, or
  - there is no recorded alert timestamp, or
  - the last alert is at least `cooldown_hours` (6h) old.
- Otherwise it remains quiet.

## 6. File map

| Path | Responsibility |
|---|---|
| `check.py` | CLI entry point, config loading, orchestration, summaries, failure alerts, healthcheck ping, `--test` |
| `config.json` | Part number, label, product URL, location, radius, cooldown, failure threshold, ntfy and email defaults |
| `checker/apple.py` | HTTP fetch, headers, retry-once, 403/429/541 → `BlockedError`, non-JSON → `ParseError` |
| `checker/parse.py` | Pure parsing of `body.stores` into `Store`/`Snapshot`; distance fallback; unknown display tracking |
| `checker/decide.py` | Pure state-diff logic returning `Alert` objects and the next state |
| `checker/notify.py` | ntfy JSON publish to server root; optional bearer token |
| `checker/emailer.py` | Resend HTTPS API and SMTP delivery; MIME/HTML builders; `NotifyError` on failure |
| `checker/state.py` | Atomic state load/save, stable sorted JSON, deep-copied defaults |
| `checker/errors.py` | `CheckerError`, `BlockedError`, `FetchError`, `ParseError`, `NotifyError` |
| `tests/test_parse.py` | Fixture parsing, unknown values, distance fallback, ineligible precedence |
| `tests/test_decide.py` | Radius, first alert, quiet rerun, cooldown, new store, disappearance/reappearance, force |
| `tests/test_emailer.py` | MIME/HTML builders, Resend payload, config validation |
| `tests/test_channels.py` | Env overrides, enabling/disabling channels, partial and total delivery failure |
| `tests/fixtures/unavailable.json` | Realistic unavailable response, includes one unknown display (R582) |
| `tests/fixtures/available.json` | **Synthetic** available response; no real in-stock capture exists yet |
| `.github/workflows/check.yml` | Hourly schedule, dispatch inputs, state restore/commit, secrets wiring |
| `config.json` ntfy `topic` | Empty by default; `NTFY_TOPIC` env/secret takes precedence |

## 7. State schema and branch mechanics

Example `state.json`:

```json
{
  "alerted": {
    "R354": "2026-10-24T17:17:03+00:00"
  },
  "failures": 0,
  "pickup": {
    "R354": {
      "distance_miles": 2.23,
      "name": "Pheasant Lane",
      "quote": "Available today at Apple Pheasant Lane"
    }
  },
  "schema": 1
}
```

Rules:

- `pickup` contains only currently available stores inside the radius.
- `alerted` timestamps exist only for stores currently available.
- `failures` resets to 0 on every successful fetch/parse.
- `failure_alerted_at` is present only after a failure notification, and is removed on success.
- On fetch/parse failure, the prior `pickup`/`alerted` maps are preserved and `failures` increments.
- On success with no alerts, `state.json` is still rewritten, but it is byte-identical, so no commit happens.

Workflow mechanics:

- Restore: `git fetch --depth=1 origin state || true`, then `git show origin/state:state.json > state.json`.
- Save: `git checkout --orphan state-update`, `git rm -rf --cached .`, `git add -f state.json`, commit, `git push --force origin HEAD:state`.
- The `state` branch contains exactly one file: `state.json`.
- The workflow creates the branch on first run; no manual branch setup is required.
- `state.json` is gitignored on the main branch.

## 8. Runtime and failure behavior

- Successful check, no availability: prints a summary, writes state, pings healthcheck, exits 0.
- Successful check, availability: sends one ntfy message and one email listing all newly available stores, then writes state and pings healthcheck.
- Fetch blocked (403/429/541): no retry, increments failures, preserves last known availability.
- Transient network/HTTP error: one retry after 2 seconds.
- 3 consecutive failures: sends `"iPhone stock checker is failing"` to both channels, at most once per 24 hours.
- Partial notification failure: logs the failed channel, records the alert if the other channel succeeded, exits 0.
- Total notification failure: exits 1 and does **not** save state, so the next hourly run retries the alert.
- `--dry-run`: never notifies, never writes state, never pings healthcheck; prints enabled channels.
- `--test`: sends a test to every enabled channel and exits without fetching. The workflow exposes this as `send_test=true`.
- Unknown `pickupDisplay` values are printed to stderr; if all values are unknown, the run is treated as a failure.

## 9. Configuration and secrets

`config.json` fields currently in use:

- `product.part_number`: `MK1H4LL/A`
- `product.label`: `iPhone Duo 512GB Night Sky (unlocked)`
- `product.url`: deep link used in notifications
- `search.location`: `03060` (overridable by `APPLE_LOCATION` or `--location`)
- `search.radius_miles`: `10.0`
- `alerts.cooldown_hours`: `6`
- `alerts.failure_threshold`: `3`
- `ntfy.enabled`: `true`
- `ntfy.server`: `https://ntfy.sh`
- `ntfy.topic`: empty; prefer the secret
- `ntfy.priority`: `5`
- `ntfy.tags`: `["iphone", "rotating_light"]`
- `email.enabled`: `true`
- `email.provider`: `resend`
- `email.from`: `iPhone Stock Checker <onboarding@resend.dev>` (overridable by `EMAIL_FROM`)
- `email.to`: empty; `ALERT_EMAIL` is required
- `email.smtp_host`, `smtp_port` (465), `smtp_security` (empty = infer: implicit TLS on 465, STARTTLS otherwise): only used when provider is `smtp`

GitHub configuration:

- Secret `NTFY_TOPIC` (required, **configured**): the user supplied a plain topic value and added it in the repository settings. A smoke test confirmed ntfy accepts it. **Never commit the topic value to this public repo.**
- Secret `NTFY_TOKEN` (optional): bearer token if a self-hosted or authenticated ntfy is used.
- Secret `ALERT_EMAIL` (**configured**): `awly.code@gmail.com`.
- Secret `RESEND_API_KEY` (**required, not set yet**): create at resend.com with **Sending access**. Until set, email delivery fails and is logged.
- Secret `EMAIL_FROM` (optional): overrides the sender; defaults to `onboarding@resend.dev`, which Resend test mode requires.
- Secret `SMTP_USERNAME` / `SMTP_PASSWORD` (optional): only for `provider: smtp`.
- Variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (optional): only for `provider: smtp`.
- Secret `HEALTHCHECK_URL` (optional): pinged after every successful check.
- Variable `APPLE_LOCATION` (optional): overrides the ZIP; falls back to `config.json`.
- `permissions: contents: write` is required for the state branch push and is already set.

The `gh` CLI is authenticated as `awllly` with a classic OAuth token (`gho_...`) carrying `repo` and `workflow` scopes. `gh workflow run`, `gh secret list/set`, and `gh variable` all work now. The earlier fine-grained PAT that returned 403 is no longer in use.

Manual dispatch:

```sh
gh workflow run check.yml --repo awllly/iphone-duo-stock-checker -f dry_run=false -f force=false
gh workflow run check.yml --repo awllly/iphone-duo-stock-checker -f send_test=true
gh run list --repo awllly/iphone-duo-stock-checker --limit 1
```

## 10. Local development

```sh
python3 -m unittest discover -s tests -v
python3 check.py --dry-run
python3 check.py --dry-run --json
python3 check.py --test --dry-run
NTFY_TOPIC=<topic> ALERT_EMAIL=<address> RESEND_API_KEY=<key> python3 check.py --test
```

Useful flags: `--config`, `--state`, `--location`, `--dry-run`, `--force`, `--json`, `--test`. All 30 tests pass on Python 3.9.6.

There is no linter or formatter configured. Keep the code stdlib-only and Python 3.9 compatible. Avoid `match`, `X | Y` at runtime, and `tomllib`.

## 11. Known risks and limitations

- **Datacenter IPs:** Apple may block GitHub Actions runners harder than a residential IP. The working local test was from a residential connection. If checks start returning 541 from Actions, the fallback is a Cloudflare Worker or a Raspberry Pi, reusing `parse.py`/`decide.py`.
- **Endpoint churn:** Apple already retired `/shop/fulfillment-messages` for this use. Assume `retail/pickup-message` can change. Fixtures plus loud failure handling are the mitigation.
- **Unobserved in-stock shape:** The real "available" response has not been captured. The synthetic fixture and the strict unknown-value handling exist for this reason. When the first real alert fires, capture the response and replace `tests/fixtures/available.json`.
- **Latency:** Detection is up to one hour late. Stock can appear and disappear between runs.
- **Quantity:** Availability does not guarantee two units; checkout quantity is still a race.
- **Privacy:** The repo is public and `config.json` contains ZIP 03060. Move it to the `APPLE_LOCATION` repo variable if that becomes a concern.
- **ntfy.sh privacy:** A plain topic is public to anyone who knows the name; the random name is the only secret. ntfy.sh also has daily message caps, which this design stays far below.
- **State branch force-push:** Intentional. Do not add branch protection that blocks force-pushes to `state`.
- **Local auth:** `gh` uses a classic OAuth token with `repo` and `workflow` scopes. If it is ever replaced by a fine-grained PAT, dispatch and secret writes may start returning 403 again; content pushes alone are not sufficient.
- **Resend test mode:** without a verified domain, Resend only sends from `onboarding@resend.dev` to the account's own email. The account must be created with `awly.code@gmail.com`, or a domain must be verified.
- **Email deliverability:** Resend/recipient filtering can put alerts in spam. The email is a backup; ntfy is primary.
- **Email dependency:** Resend is a third-party HTTP dependency. If it is down, ntfy still works; if ntfy is down, email still works.

## 12. Next steps

1. Add the `RESEND_API_KEY` secret (Sending access) from a Resend account created with `awly.code@gmail.com`.
2. Dispatch `send_test=true` and confirm both ntfy and email arrive; check spam.
3. The cron runs hourly at minute 17 with no further action. Optionally confirm scheduled runs are succeeding.
4. Create a Healthchecks.io check pointing its webhook at ntfy so a dead checker is noticed, then add `HEALTHCHECK_URL`.
5. When the first real alert fires, capture the raw response and replace `tests/fixtures/available.json`; also capture the email/ntfy pair as a reference.
6. Phase 2 (only if requested): find a working delivery-ETA source and alert on ETA improvement, not on the mere existence of a date.

## 13. Do not

- Do not switch back to `/shop/fulfillment-messages`; it returns 541.
- Do not treat blocked/failed requests as "out of stock."
- Do not remove the "unknown display" handling; it is the guard against silent breakage.
- Do not add third-party dependencies without a strong reason; the job's speed and reliability depend on the stdlib-only design.
- Do not commit `state.json` to the main branch; it lives only on the `state` branch.
- Do not commit the Resend API key, the recipient email, or SMTP credentials; they belong in repository secrets.
- Do not log API keys or full credentials; `NotifyError` messages only include provider status/details.
- Do not change the schedule without updating this file and the README.
