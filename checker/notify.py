import json
import urllib.error
import urllib.request

from .errors import NotifyError

USER_AGENT = "ipchecker/1.0"


def send(
    server,
    topic,
    title,
    message,
    click=None,
    priority=5,
    tags=None,
    token=None,
    timeout=15,
):
    if not topic:
        raise NotifyError("NTFY_TOPIC is not set")

    payload = {"topic": topic, "title": title, "message": message, "priority": priority}
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "Buy now", "url": click, "clear": True}]
    if tags:
        payload["tags"] = tags

    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = "Bearer %s" % token

    request = urllib.request.Request(
        server.rstrip("/"),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            if response.status >= 300:
                raise NotifyError("ntfy returned HTTP %d" % response.status)
    except urllib.error.HTTPError as exc:
        raise NotifyError("ntfy returned HTTP %d" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise NotifyError("ntfy request failed: %s" % exc.reason) from exc
