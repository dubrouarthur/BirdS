"""Repair the common argument-shape mistakes of a small model BEFORE schema validation.

Nothing here widens what is accepted: every value still goes through the JSON schema afterwards. We only turn a
value into the type the schema asks for when the intent is unambiguous:

- an array or object written as a JSON string (``"slides": "[{...}]"``), even when the model forgot the last
  closing bracket(s) or left a trailing comma (the real make_slides failure seen on the live endpoint);
- a number or boolean written as a string (``"5"``, ``"12,5"``, ``"true"``);
- a single object or a single string where the schema wants a list of them;
- a list of strings given as one string with one item per line or separated by commas (``to``, ``bullets``);
- in ``make_sheet``, rows given as objects keyed by column name, or a row given as a JSON string.

Each repair is recorded so the audit log can say what was changed.
"""

from __future__ import annotations

import ast
import json
import re

_BULLET = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")


def _balance(text: str) -> str:
    """Close brackets/braces/quotes left open at the end of a JSON text and drop trailing commas."""
    stack, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append("]" if ch == "[" else "}")
        elif ch in "]}" and stack and stack[-1] == ch:
            stack.pop()
    out = text + ('"' if in_str else "")
    out = re.sub(r",\s*$", "", out)
    return out + "".join(reversed(stack))


def parse_json_like(text: str):
    """Best-effort decoding of a JSON array/object written by a model. Raises ValueError when hopeless."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s)
    candidates = [s, re.sub(r",\s*([\]}])", r"\1", s)]
    candidates.append(_balance(candidates[-1]))
    for c in candidates:
        try:
            return json.loads(c)
        except ValueError:
            pass
    try:  # Python-style literal: single quotes, True/False/None
        return ast.literal_eval(_balance(s))
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        raise ValueError("not JSON") from None


def _types(spec: dict) -> list[str]:
    t = spec.get("type")
    return t if isinstance(t, list) else [t] if t else []


def _number(text: str):
    s = text.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?\d*[.,]\d+", s):
        return float(s.replace(",", "."))
    raise ValueError


def _split_list(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return [_BULLET.sub("", ln).strip() for ln in lines]
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
    return parts if len(parts) > 1 else [_BULLET.sub("", text).strip()]


def coerce(value, spec: dict, path: str, notes: list[str]):
    """Return ``value`` converted towards ``spec`` when the intent is clear; otherwise return it unchanged."""
    types = _types(spec)
    if not types or ("string" in types and isinstance(value, str)):
        return value
    if isinstance(value, str) and ("array" in types or "object" in types):
        s = value.strip()
        if s[:1] in "[{" or s.startswith("```"):
            try:
                decoded = parse_json_like(s)
                notes.append(f"{path}: JSON text decoded")
                return coerce(decoded, spec, path, notes)
            except ValueError:
                pass
        if "array" in types and _types(spec.get("items") or {}) == ["string"] and s:
            notes.append(f"{path}: text split into a list")
            return _split_list(s)
        return value
    if isinstance(value, str) and ("integer" in types or "number" in types):
        try:
            n = _number(value)
        except ValueError:
            return value
        if "integer" in types and isinstance(n, float) and n.is_integer():
            n = int(n)
        if "integer" in types and not isinstance(n, int) and "number" not in types:
            return value
        notes.append(f"{path}: number read from text")
        return n
    if isinstance(value, str) and "boolean" in types and value.strip().lower() in ("true", "false", "oui", "non"):
        notes.append(f"{path}: boolean read from text")
        return value.strip().lower() in ("true", "oui")
    if "array" in types and not isinstance(value, list) and value is not None:
        item_types = _types(spec.get("items") or {})
        if isinstance(value, dict) and "object" in item_types:
            notes.append(f"{path}: single object wrapped in a list")
            return coerce([value], spec, path, notes)
        if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            notes.append(f"{path}: object of objects turned into a list")  # {"1": {...}, "2": {...}}
            return coerce(list(value.values()), spec, path, notes)
        return value
    if isinstance(value, list) and "array" in types:
        items = spec.get("items") or {}
        return [coerce(v, items, f"{path}/{i}", notes) for i, v in enumerate(value)]
    if isinstance(value, dict) and "object" in types:
        props = spec.get("properties") or {}
        return {k: coerce(v, props[k], f"{path}/{k}", notes) if k in props else v for k, v in value.items()}
    return value


def _sheet_rows(args: dict, notes: list[str]) -> None:
    """make_sheet: rows written as objects (column -> value) become lists in column order."""
    cols, rows = args.get("columns"), args.get("rows")
    if not isinstance(rows, list) or not isinstance(cols, list):
        return
    fixed, changed = [], False
    for row in rows:
        if isinstance(row, dict):
            row, changed = [row.get(c) for c in cols], True
        elif isinstance(row, str):
            try:
                decoded = parse_json_like(row)
            except ValueError:
                decoded = None
            if isinstance(decoded, list):
                row, changed = decoded, True
        fixed.append(row)
    if changed:
        notes.append("rows: objects or JSON text turned into lists")
        args["rows"] = fixed


_ALIASES = {  # tool -> (list argument, {expected key: [names a model uses instead]})
    "make_slides": ("slides", {"bullets": ["points", "items", "content", "text", "body"], "title": ["heading"]}),
    "make_document": ("sections", {"heading": ["title", "name"], "content": ["text", "body", "paragraphs"]}),
}


def _rename(args: dict, tool: str, notes: list[str]) -> None:
    """An item that lacks a required key but carries an obvious synonym gets the synonym renamed."""
    key, table = _ALIASES.get(tool, (None, {}))
    items = args.get(key)
    if not isinstance(items, list):
        return
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for want, alts in table.items():
            if want in item:
                continue
            alt = next((a for a in alts if a in item), None)
            if alt is not None:
                item[want] = item.pop(alt)
                notes.append(f"{key}/{i}: '{alt}' read as '{want}'")


def coerce_args(tool: str, args: dict, schema: dict) -> tuple[dict, list[str]]:
    """(repaired arguments, notes). Unknown keys are kept: validation refuses them afterwards."""
    notes: list[str] = []
    props = schema.get("properties") or {}
    out = {k: coerce(v, props[k], k, notes) if k in props else v for k, v in args.items()}
    if tool in _ALIASES:
        _rename(out, tool, notes)
        key = _ALIASES[tool][0]
        if key in out:  # second pass: renamed values (e.g. "content" text -> bullets list) get their types fixed
            out[key] = coerce(out[key], props[key], key, notes)
    if tool in _FLAT_ALIASES:
        _flat(out, tool, notes)
    if tool == "make_sheet":
        _sheet_rows(out, notes)
        if isinstance(out.get("rows"), list):
            out["rows"] = coerce(out["rows"], props["rows"], "rows", notes)
    return out, notes


_FLAT_ALIASES = {  # routed widget tools: flat arguments a small model names differently
    "find_places": {
        "query": ["q", "place", "location", "address", "adresse", "lieu", "name", "search"],
        "near": ["around", "near_to", "location_near", "autour", "pres_de", "close_to"],
    },
    "find_company": {"name": ["query", "company", "siren", "siret", "q", "nom", "entreprise"]},
    "convert_currency": {
        "from": ["from_currency", "source", "base", "currency_from", "de"],
        "to": ["to_currency", "target", "quote", "currency_to", "en", "vers"],
        "amount": ["value", "montant", "somme", "quantity"],
    },
}


def _flat(args: dict, tool: str, notes: list[str]) -> None:
    for want, alts in _FLAT_ALIASES[tool].items():
        if want in args:
            continue
        alt = next((a for a in alts if a in args), None)
        if alt is not None:
            args[want] = args.pop(alt)
            notes.append(f"'{alt}' read as '{want}'")
    if tool == "find_places" and isinstance(args.get("query"), str) and not args.get("near"):
        from birds.harness.intents import split_near

        pair = split_near(args["query"])
        if pair:
            args["query"], args["near"] = pair
            notes.append("query 'X near Y' split into query and near")
    if tool == "convert_currency":
        from birds.harness.intents import currency_code, parse_amount

        for k in ("from", "to"):
            v = args.get(k)
            if isinstance(v, str) and len(v) != 3:
                code = currency_code(v)
                if code:
                    args[k], _ = code, notes.append(f"{k}: '{v}' read as {code}")
            elif isinstance(v, str) and v != v.upper():
                args[k] = v.upper()
        v = args.get("amount")
        if isinstance(v, str):
            amt = parse_amount(re.sub(r"[^\d.,  kKmM]", "", v))
            if amt is not None:
                args["amount"] = amt
                notes.append(f"amount: '{v}' read as {amt:g}")
