# Session Memory — iPhone Duo Stock Checker

Last updated: 2026-10-24
Status: deployed to https://github.com/awllly/iphone-duo-stock-checker and verified on GitHub Actions. The required `NTFY_TOPIC` secret is not yet configured because the local fine-grained PAT cannot write Actions secrets.

This file is the handoff context for a new AI agent or developer. Read it before changing anything.

## 1. What the user asked for

A free service that checks Apple stock for one specific iPhone and sends a push notification to their iPhone when it becomes available.

User requirements, as confirmed:

- Target: **iPhone Duo** (the 2026 foldable; "Duo" is the model name, not a quantity), **512 GB**, **Night Sky**, **unlocked / "Connect on your own later"**.
- Location: ZIP **03060** (Nashua, NH area). Search radius: **10 miles**.
- Wants both in-store pickup and online delivery awareness. **v1 is pickup only**; delivery was explicitly deferred.
- Hosting: **GitHub Actions**, free tier, **public repo** is acceptable.
- Alerts: **ntfy**, one iPhone, **plain secret topic** (no ntfy account/token required, though token support exists).
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
- Python 3.9-compatible, stdlib-only checker (`urllib`, `json`, `dataclasses`, `unittest`). No `requirements.txt`, no pip install step.
- Apple pickup fetcher with block detection and one retry.
- Parser with strict unknown-value handling.
- Alert decision logic: new store, 6-hour reminder cooldown, force mode.
- ntfy publisher with title, priority, tags, click URL, and a "Buy now" action.
- State load/save with stable key ordering.
- Hourly GitHub Actions workflow at minute 17, with manual dispatch (`dry_run`, `force`), concurrency guard, and orphan-commit state branch updates.
- 14 unit tests using fixtures.
- ntfy publish verified with HTTP 200 against a throwaway topic.
- State-branch orphan commit + force-push flow verified in production.
- Two consecutive live runs produced byte-identical `state.json` (no commit noise).

Outstanding:

- **`NTFY_TOPIC` secret is not set.** The authenticated fine-grained PAT can push contents but returns 403 for Actions secrets, variables, permissions, and workflow dispatch. Until this is fixed, a stock alert will fail at the notification step (the run exits 1 and does not save state).
- No real in-stock event has been observed, so the "available" fixture is synthetic.
- Delivery ETA is not implemented and has no known working endpoint.
- No Healthchecks.io check created yet (code supports `HEALTHCHECK_URL`).
- `gh workflow run` and `gh secret set` do not work with the current PAT. The scheduled cron runs independently of the token.

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

## 5. Architecture and data flow

```
GitHub Actions (hourly, :17)
  -> restore state.json from origin/state (if present)
  -> python3 check.py
       -> checker.apple.fetch_pickup([MK1H4LL/A], location)
       -> checker.parse.parse_pickup(...)
       -> checker.decide.evaluate(snapshot, state, radius, cooldown)
       -> checker.notify.send(...) only if alerts
       -> checker.state.save(...)
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
| `config.json` | Part number, label, product URL, location, radius, cooldown, failure threshold, ntfy defaults |
| `checker/apple.py` | HTTP fetch, headers, retry-once, 403/429/541 → `BlockedError`, non-JSON → `ParseError` |
| `checker/parse.py` | Pure parsing of `body.stores` into `Store`/`Snapshot`; distance fallback; unknown display tracking |
| `checker/decide.py` | Pure state-diff logic returning `Alert` objects and the next state |
| `checker/notify.py` | ntfy JSON publish to server root; optional bearer token |
| `checker/state.py` | Atomic state load/save, stable sorted JSON, deep-copied defaults |
| `checker/errors.py` | `CheckerError`, `BlockedError`, `FetchError`, `ParseError`, `NotifyError` |
| `tests/test_parse.py` | Fixture parsing, unknown values, distance fallback, ineligible precedence |
| `tests/test_decide.py` | Radius, first alert, quiet rerun, cooldown, new store, disappearance/reappearance, force |
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
- Successful check, availability: sends one ntfy message listing all newly available stores, then writes state and pings healthcheck.
- Fetch blocked (403/429/541): no retry, increments failures, preserves last known availability.
- Transient network/HTTP error: one retry after 2 seconds.
- 3 consecutive failures: sends `"iPhone stock checker is failing"` at priority 4, at most once per 24 hours.
- Notification failure: exits 1 and does **not** save state, so the next hourly run retries the alert.
- `--dry-run`: never notifies, never writes state, never pings healthcheck.
- `--test`: publishes a test notification and exits without fetching.
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
- `ntfy.server`: `https://ntfy.sh`
- `ntfy.topic`: empty; prefer the secret
- `ntfy.priority`: `5`
- `ntfy.tags`: `["iphone", "rotating_light"]`

GitHub configuration:

- Secret `NTFY_TOPIC` (required, **not currently set**): the user supplied a plain topic value. Add it at
  `https://github.com/awllly/iphone-duo-stock-checker/settings/secrets/actions` or with an authenticated CLI:
  `gh secret set NTFY_TOPIC --body "<topic>" --repo awllly/iphone-duo-stock-checker`.
  **Never commit the topic value to this public repo.**
- Secret `NTFY_TOKEN` (optional): bearer token if a self-hosted or authenticated ntfy is used.
- Secret `HEALTHCHECK_URL` (optional): pinged after every successful check.
- Variable `APPLE_LOCATION` (optional): overrides the ZIP; falls back to `config.json`.
- `permissions: contents: write` is required for the state branch push and is already set.

The current fine-grained PAT can read workflows and push contents, but cannot write Actions secrets, variables, permissions, or dispatch workflows. Use the web UI for those operations, or re-authenticate with a classic OAuth token:

```sh
gh auth login -h github.com -s repo,workflow -w
```

## 10. Local development

```sh
python3 -m unittest discover -s tests -v
python3 check.py --dry-run
python3 check.py --dry-run --json
NTFY_TOPIC=<topic> python3 check.py --test
```

Useful flags: `--config`, `--state`, `--location`, `--dry-run`, `--force`, `--json`, `--test`.

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
- **Local PAT limits:** content pushes work, but Actions secrets, variables, permissions, and workflow dispatch return 403. The scheduled workflow runs regardless of the local token.

## 12. Next steps

1. Add the `NTFY_TOPIC` secret in the GitHub web UI (or re-authenticate first). This is the only thing blocking live alerts.
2. Subscribe to the same topic in the ntfy iOS app.
3. Run `python3 check.py --test` locally with `NTFY_TOPIC` exported to confirm the phone receives it, or use the web UI's "Run workflow" with `dry_run: true` to re-verify the fetch.
4. The cron will run hourly at minute 17 with no further action. Confirm at least one scheduled run succeeds.
5. Create a Healthchecks.io check pointing its webhook at ntfy so a dead checker is noticed, then add `HEALTHCHECK_URL`.
6. When the first real alert fires, capture the raw response and replace `tests/fixtures/available.json`.
7. Phase 2 (only if requested): find a working delivery-ETA source and alert on ETA improvement, not on the mere existence of a date.

## 13. Do not

- Do not switch back to `/shop/fulfillment-messages`; it returns 541.
- Do not treat blocked/failed requests as "out of stock."
- Do not remove the "unknown display" handling; it is the guard against silent breakage.
- Do not add third-party dependencies without a strong reason; the job's speed and reliability depend on the stdlib-only design.
- Do not commit `state.json` to the main branch; it lives only on the `state` branch.
- Do not change the schedule without updating this file and the README.
