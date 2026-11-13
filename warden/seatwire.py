"""Plain messages for a seat that runs in its own process.

A seat in its own process cannot be handed Python objects, only text. This module turns the rows Warden and
the seats agree on (the frozen dataclasses and string enums of `cns` and `warden`) into JSON and back.

Only classes from `cns.*` and `warden.*` that are dataclasses or enums are rebuilt. A message naming anything
else is refused, so a seat cannot make Warden construct an arbitrary object by naming it. A value that cannot
be written as JSON (a set, bytes, an object of another class) is an error, never a quiet guess: the run ends
as ERROR and says so.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import json
import math
from typing import Any

_ALLOWED_PREFIXES = ("cns.", "warden.")


class WireError(ValueError):
    """A value could not be sent, or a message could not be read."""


def _class_name(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _allowed(module: str) -> bool:
    return module.startswith(_ALLOWED_PREFIXES)


def to_wire(value: Any) -> Any:
    """`value` as something `json.dumps` accepts, with the type of every row and tuple kept."""
    if value is None or isinstance(value, (bool, str)) and not isinstance(value, enum.Enum):
        return value
    if isinstance(value, enum.Enum):
        cls = type(value)
        if not _allowed(cls.__module__):
            raise WireError(f"an enum of {_class_name(cls)} cannot be sent to a seat")
        return {"__enum__": _class_name(cls), "value": value.value}
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WireError("a number that is not finite cannot be sent to a seat")
        return value
    if isinstance(value, tuple):
        return {"__tuple__": [to_wire(v) for v in value]}
    if isinstance(value, list):
        return [to_wire(v) for v in value]
    if isinstance(value, dict) or hasattr(value, "keys") and hasattr(value, "__getitem__"):
        out = {}
        for key in value.keys():
            if not isinstance(key, str):
                raise WireError(f"a mapping key {key!r} is not text, so it cannot be sent to a seat")
            out[key] = to_wire(value[key])
        if any(k.startswith("__") and k.endswith("__") for k in out):
            raise WireError("a mapping with a key of the form __name__ cannot be sent to a seat")
        return out
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        row_cls = type(value)
        if not _allowed(row_cls.__module__):
            raise WireError(f"a row of {_class_name(row_cls)} cannot be sent to a seat")
        fields = {f.name: to_wire(getattr(value, f.name)) for f in dataclasses.fields(value) if f.init}
        return {"__row__": _class_name(row_cls), "fields": fields}
    raise WireError(f"a value of type {type(value).__name__} cannot be sent to a seat")


def _resolve(name: str, wanted: str) -> type:
    module_name, _, qualname = name.partition(":")
    if not _allowed(module_name + ".") and not _allowed(module_name):
        raise WireError(f"the message names {name!r}, which is not a class Warden or CNS defines")
    obj: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if wanted == "enum" and not (isinstance(obj, type) and issubclass(obj, enum.Enum)):
        raise WireError(f"{name!r} is not an enum")
    if wanted == "row" and not (isinstance(obj, type) and dataclasses.is_dataclass(obj)):
        raise WireError(f"{name!r} is not a row")
    return obj


def from_wire(data: Any) -> Any:
    """The reverse of `to_wire`. Mappings come back as plain dicts."""
    if isinstance(data, list):
        return [from_wire(v) for v in data]
    if not isinstance(data, dict):
        return data
    if "__tuple__" in data:
        return tuple(from_wire(v) for v in data["__tuple__"])
    if "__enum__" in data:
        return _resolve(data["__enum__"], "enum")(data["value"])
    if "__row__" in data:
        cls = _resolve(data["__row__"], "row")
        return cls(**{k: from_wire(v) for k, v in data["fields"].items()})
    return {k: from_wire(v) for k, v in data.items()}


def dumps(message: dict) -> str:
    """One message as a single line of JSON."""
    try:
        return json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WireError(f"a message could not be written: {exc}") from None


def loads(line: str) -> dict:
    try:
        message = json.loads(line)
    except ValueError as exc:
        raise WireError(f"a message could not be read: {exc}") from None
    if not isinstance(message, dict):
        raise WireError("a message was not an object")
    return message
