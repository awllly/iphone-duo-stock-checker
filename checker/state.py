import copy
import json
import os
from pathlib import Path

DEFAULTS = {"schema": 1, "pickup": {}, "alerted": {}, "failures": 0}


def load(path):
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULTS)
    for key, value in DEFAULTS.items():
        data.setdefault(key, value)
    return data


def dumps(state):
    return json.dumps(state, indent=2, sort_keys=True) + "\n"


def save(path, state):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(state), encoding="utf-8")
    os.replace(tmp, path)
