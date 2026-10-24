import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import BlockedError, FetchError, ParseError

PICKUP_URL = "https://www.apple.com/shop/retail/pickup-message"
PRODUCT_URL = (
    "https://www.apple.com/shop/buy-iphone/iphone-duo/"
    "7.6-inch-display-512gb-night-sky-unlocked"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BLOCKED_STATUSES = {403, 429, 541}


def _fetch_once(part_numbers, location, timeout):
    params = [("location", location)]
    for index, part in enumerate(part_numbers):
        params.append(("parts.%d" % index, part))
    url = PICKUP_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": PRODUCT_URL,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code in BLOCKED_STATUSES:
            raise BlockedError("Apple returned HTTP %d" % exc.code) from exc
        raise FetchError("Apple returned HTTP %d" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise FetchError("request failed: %s" % exc.reason) from exc

    if status != 200:
        raise FetchError("Apple returned HTTP %d" % status)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ParseError("Apple response was not JSON") from exc


def fetch_pickup(part_numbers, location, timeout=20, retries=1):
    last_error = None
    for attempt in range(retries + 1):
        try:
            return _fetch_once(part_numbers, location, timeout)
        except BlockedError:
            raise
        except FetchError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2)
    raise last_error
