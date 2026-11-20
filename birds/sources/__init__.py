"""Source registry contract.

A source module (birds/sources/<group>.py) exports `SOURCES: list[Source]`.

`convert(row)` receives one upstream row (dict) and returns a list of records WITHOUT the
bookkeeping fields: each item needs only `messages`, `lang`, `thinking`, and optionally `tools`
and `task`. The builder adds id/source/license, validates with birds.schema, de-duplicates and caps.
Return [] to skip a row. Converters must be pure, deterministic and must not raise on odd rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Source:
    name: str  # short key, e.g. "toucan"
    repo: str  # Hub dataset id
    license: str  # license of the rows we keep
    task: str  # default task tag
    cap: int  # max records kept in the v0 mix
    convert: Callable[[dict], list[dict]]
    config: str | None = None
    split: str = "train"
    data_files: str | list[str] | None = None  # when the repo needs explicit files
    scan: int = 0  # upstream rows to read at most (0 = 6 x cap)
    note: str = ""
    kwargs: dict = field(default_factory=dict)  # extra load_dataset arguments


def all_sources() -> list[Source]:
    import importlib
    import pkgutil

    out: list[Source] = []
    for m in pkgutil.iter_modules(__path__):
        out += list(getattr(importlib.import_module(f"{__name__}.{m.name}"), "SOURCES", []))
    names = [s.name for s in out]
    assert len(names) == len(set(names)), "duplicate source names"
    return out
