"""Output helpers — Rich tables for humans, JSON for scripts/skills."""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def emit(payload: Any, *, as_json: bool, render_human=None) -> None:
    """Emit `payload`. If `as_json`, dump JSON. Otherwise call `render_human(payload)`.

    If `render_human` is None, falls back to JSON-pretty output.
    """
    if as_json or render_human is None:
        console.print_json(json.dumps(payload, default=str))
    else:
        render_human(payload)


def status_table(rows: Iterable[tuple[str, str, str]]) -> Table:
    """Build a 3-column status table: (component, status, detail)."""
    t = Table(show_header=True, header_style="bold")
    t.add_column("Component")
    t.add_column("Status")
    t.add_column("Detail")
    for name, status, detail in rows:
        style = "green" if status.lower() in ("ok", "ready") else "red"
        t.add_row(name, f"[{style}]{status}[/{style}]", detail)
    return t
