"""Follow-up turns change the current artifact instead of regenerating it.

Three ways in, from the cheapest:

1. ``direct_ops``: the user's words alone name the change (« supprime la diapo 3 », « thème chaleureux »,
   « remplace l'image de la slide 2 par une photo de tramway », « inverse les slides 2 et 3 »). The harness applies
   it without any model call.
2. ``parse_patch``: the model was given the outline with block ids and wrote targeted operations
   (``@replace b3`` + the new block, ``@after b4``, ``@delete b2``, ``@theme warm``). Lenient: French verbs, a
   missing ``@``, a block that kept its ``[b3]`` tag (= replace b3), new blocks with no directive (placed where the
   user said, else before the closing slide), or the whole deck written again (a full rewrite, ids kept by title).
3. ``apply``: the operations, checked one by one (an unknown id is reported, never guessed silently).
"""

from __future__ import annotations

import re

from . import dsl

# ------------------------------------------------------------------ applying operations


def _index(doc: dict, bid: str | None) -> int:
    for i, b in enumerate(doc.get("blocks") or []):
        if b.get("id") == bid:
            return i
    return -1


def _fresh(doc: dict, block: dict, keep_id: str | None = None) -> dict:
    b = {"id": keep_id or dsl.new_id(doc), "title": str(block.get("title") or ""), "parts": list(block.get("parts") or []),
         "notes": str(block.get("notes") or "")}  # fmt: skip
    return b


def apply(doc: dict, ops: list[dict]) -> tuple[dict, list[str], list[str]]:
    """(new document, what was done, what could not be done). The input document is not modified."""
    out = dsl.clone(doc)
    out.setdefault("blocks", [])
    done, failed = [], []
    for op in ops or []:
        kind = op.get("op")
        blocks = out["blocks"]
        if kind == "replace":
            i = _index(out, op.get("id"))
            if i < 0:
                failed.append(f"replace: no block {op.get('id')}")
                continue
            nb = _fresh(out, op["block"], blocks[i]["id"])
            if not nb["title"]:
                nb["title"] = blocks[i].get("title") or ""  # « @replace b3 » followed by bullets only
            blocks[i] = nb
            done.append(f"replace {blocks[i]['id']}")
        elif kind == "insert":
            if len(blocks) >= dsl.MAX_BLOCKS:
                failed.append("insert: the document is full")
                continue
            after = op.get("after")
            if after in (None, "start"):
                at = 0
            elif after == "end":
                at = len(blocks)
            else:
                i = _index(out, after)
                if i < 0:
                    failed.append(f"insert: no block {after}, added at the end")
                    i = len(blocks) - 1
                at = i + 1
            nb = _fresh(out, op["block"])
            blocks.insert(at, nb)
            done.append(f"insert {nb['id']}")
        elif kind == "delete":
            i = _index(out, op.get("id"))
            if i < 0:
                failed.append(f"delete: no block {op.get('id')}")
                continue
            if len(blocks) == 1:
                failed.append("delete: the last block is kept")
                continue
            blocks.pop(i)
            done.append(f"delete {op.get('id')}")
        elif kind == "move":
            i = _index(out, op.get("id"))
            if i < 0:
                failed.append(f"move: no block {op.get('id')}")
                continue
            b = blocks.pop(i)
            after = op.get("after")
            if after in (None, "start"):
                at = 0
            elif after == "end":
                at = len(blocks)
            else:
                j = _index(out, after)
                if j < 0:
                    blocks.insert(i, b)
                    failed.append(f"move: no block {after}")
                    continue
                at = j + 1
            blocks.insert(at, b)
            done.append(f"move {b['id']}")
        elif kind == "swap":
            i, j = _index(out, op.get("id")), _index(out, op.get("other"))
            if i < 0 or j < 0:
                failed.append("swap: unknown block")
                continue
            blocks[i], blocks[j] = blocks[j], blocks[i]
            done.append(f"swap {op.get('id')} {op.get('other')}")
        elif kind == "duplicate":
            i = _index(out, op.get("id"))
            if i < 0 or len(blocks) >= dsl.MAX_BLOCKS:
                failed.append(f"duplicate: no block {op.get('id')}")
                continue
            nb = _fresh(out, dsl.clone(blocks[i]))
            blocks.insert(i + 1, nb)
            done.append(f"duplicate {blocks[i]['id']} -> {nb['id']}")
        elif kind == "theme":
            name = dsl.theme_of(op.get("theme")) or (op.get("theme") if op.get("theme") in dsl.THEMES else None)
            if not name:
                failed.append("theme: unknown theme")
                continue
            out["theme"] = name
            done.append(f"theme {name}")
        elif kind == "meta":
            for k in ("title", "subtitle"):
                if isinstance(op.get(k), str):
                    out[k] = dsl._cut(op[k].strip(), dsl.MAX_TITLE)
                    done.append(k)
        elif kind == "retitle":
            i = _index(out, op.get("id"))
            if i < 0:
                failed.append(f"retitle: no block {op.get('id')}")
                continue
            blocks[i]["title"] = dsl._cut(str(op.get("title") or "").strip(), dsl.MAX_TITLE)
            done.append(f"retitle {op.get('id')}")
        elif kind in ("image", "unimage"):
            i = _index(out, op.get("id"))
            if i < 0:
                failed.append(f"{kind}: no block {op.get('id')}")
                continue
            parts = blocks[i]["parts"]
            k = next((n for n, p in enumerate(parts) if p.get("t") == "image"), -1)
            if kind == "unimage":
                if k >= 0:
                    parts.pop(k)
                    done.append(f"unimage {op['id']}")
                else:
                    failed.append(f"unimage: block {op['id']} has no picture")
                continue
            old = parts[k] if k >= 0 else {}
            query = str(op.get("query") or old.get("query") or blocks[i]["title"] or out.get("title") or "")[:120]
            new = {"t": "image", "query": query, "alt": query, "caption": ""}
            if op.get("again") and old.get("media"):
                new["exclude"] = [old["media"], *[x for x in old.get("exclude", []) if isinstance(x, str)]][:8]
            if k >= 0:
                parts[k] = new
            else:
                parts.append(new)
            done.append(f"image {op['id']}")
        else:
            failed.append(f"unknown operation {kind!r}")
    return out, done, failed


# ------------------------------------------------------------------ the user's words: block references

_UNIT = r"(?:slides?|diapos?(?:itives?)?|transparents?|pages?|sections?|parties|partie|blocs?|paragraphes?|chapitres?)"
_ORD = {
    "première": 1, "premiere": 1, "premier": 1, "first": 1, "deuxième": 2, "deuxieme": 2, "seconde": 2, "second": 2,
    "troisième": 3, "troisieme": 3, "third": 3, "quatrième": 4, "quatrieme": 4, "fourth": 4, "cinquième": 5,
    "cinquieme": 5, "fifth": 5, "sixième": 6, "sixieme": 6, "sixth": 6, "dernière": -1, "derniere": -1, "dernier": -1,
    "last": -1,
}  # fmt: skip
_REF = re.compile(
    rf"\b(?:(?:la|le|les|the|du|de la|of)\s+)?(?:{_UNIT})\s*(?:n°\s*|no\.?\s*|numéro\s*|number\s*)?(\d{{1,2}})\b|"
    rf"\b(?:la|le|the)\s+(première|premiere|premier|first|deuxième|deuxieme|seconde|second|troisième|troisieme|third|"
    rf"quatrième|quatrieme|fourth|cinquième|cinquieme|fifth|sixième|sixieme|sixth|dernière|derniere|dernier|last)\s+"
    rf"{_UNIT}|\b{_UNIT}\s+(\d{{1,2}})\b|\b(b\d{{1,3}})\b",
    re.I,
)


def refs(words: str, doc: dict) -> list[str]:
    """Block ids the user's words point at, in order: « la diapo 3 », « slide n°2 », « la dernière section »,
    « b4 »; a slide number counts the cover as slide 1 when the deck shows one (it always does)."""
    blocks = doc.get("blocks") or []
    out = []
    for m in _REF.finditer(words or ""):
        num, ordw, num2, bid = m.group(1), m.group(2), m.group(3), m.group(4)
        n = None
        if num or num2:
            n = int(num or num2)
        elif ordw:
            n = _ORD.get(ordw.lower())
        if bid:
            if _index(doc, bid.lower()) >= 0:
                out.append(bid.lower())
            continue
        if n is None:
            continue
        idx = len(blocks) - 1 if n == -1 else n - 1
        if 0 <= idx < len(blocks):
            out.append(blocks[idx]["id"])
    # « slides 2 et 3 », « les diapos 2, 3 et 4 »
    m = re.search(rf"\b{_UNIT}\s+(\d{{1,2}})((?:\s*(?:,|et|and|&)\s*\d{{1,2}})+)", words or "", re.I)
    if m:
        for x in re.findall(r"\d{1,2}", m.group(2)):
            idx = int(x) - 1
            if 0 <= idx < len(blocks) and blocks[idx]["id"] not in out:
                out.append(blocks[idx]["id"])
    return out


_DELETE = re.compile(r"\b(?:supprime[rz]?|enl[eè]ve[rz]?|retire[rz]?|efface[rz]?|vire[rz]?|delete|remove|drop)\b", re.I)
_DUP = re.compile(r"\b(?:duplique[rz]?|dupliquer|copie[rz]? (?:la|le)|duplicate|clone)\b", re.I)
_MOVE = re.compile(r"\b(?:d[ée]place[rz]?|mets?|mettre|passe[rz]?|remonte[rz]?|descend[sz]?|move|put)\b", re.I)
_SWAP = re.compile(r"\b(?:inverse[rz]?|[ée]change[rz]?|permute[rz]?|swap)\b", re.I)
_THEME_WORD = re.compile(r"\b(?:th[eè]me|style|look|habillage|couleurs?|palette|design|theme)\b", re.I)
_THEME_NAME = re.compile(
    r"\b(sobre|corporate|classique|institutionnel|moderne?|modern|tech|chaleureu(?:x|se)|warm|chaud)\b", re.I
)
_IMAGE_WORD = re.compile(r"\b(?:images?|photos?|illustrations?|visuels?|pictures?|picture)\b", re.I)
_REPLACE = re.compile(r"\b(?:remplace[rz]?|change[rz]?|modifie[rz]?|autre|nouvelle|replace|swap|another|different)\b",
                      re.I)  # fmt: skip
_ADD_IMAGE = re.compile(r"\b(?:ajoute[rz]?|mets?|ins[èe]re[rz]?|add|insert|put)\b", re.I)
_RENAME = re.compile(r"\b(?:renomme[rz]?|rename|retitle|change[rz]? le titre|titre)\b", re.I)


def _image_query(words: str) -> str:
    """« … par une photo de tramway à Lyon » -> 'tramway à Lyon'."""
    text = words.strip()
    lead = re.search(r"\b(?:par|avec|with|by)\s+(?P<rest>[^.?!]{2,100})$", text, re.I)
    if not lead:
        return ""
    m = re.match(
        r"(?:une?|des|la|le|les|an?|the)?\s*(?:(?:autre|nouvelle|another|new)\s+)?"
        r"(?:images?|photos?|illustrations?|visuels?|pictures?)?\s*"
        r"(?:de|d['’]|du|des|of|showing|montrant|représentant|sur)?\s*(?P<q>.{2,80})$",
        lead.group("rest").strip(),
        re.I,
    )
    if not m:
        return ""
    q = m.group("q").strip(" .,;:")
    q = re.sub(rf"^(?:la|le|les|l['’])?\s*{_UNIT}\s*\d+\s*", "", q, flags=re.I).strip()
    if _IMAGE_WORD.fullmatch(q) or not q or re.fullmatch(r"(?:la|le|une|un|the|a)\b.*", q, re.I) and len(q) < 6:
        return ""
    return q


# Words that make a change uncertain: a negation (« ne mets pas »), a contrast (« plutôt que de la supprimer »,
# « sans »), a question or a hesitation (« non attends, laisse »). The model reads those, never a regex.
_UNSURE = re.compile(
    r"\b(?:ne|n['’]|pas|jamais|plut[ôo]t|sans|sauf|non|attends?|laisse[rz]?|surtout|h[ée]site|peut-[êe]tre|"
    r"not|don['’]?t|never|instead|rather|without|except|wait|maybe)\b|\?",
    re.I,
)
_ACTION = re.compile(
    r"\b(?:supprime[rz]?|enl[eè]ve[rz]?|retire[rz]?|efface[rz]?|vire[rz]?|delete|remove|drop|duplique[rz]?|"
    r"dupliquer|copie[rz]?|duplicate|clone|d[ée]place[rz]?|mets?|mettre|passe[rz]?|remonte[rz]?|descend[sz]?|move|"
    r"put|inverse[rz]?|[ée]change[rz]?|permute[rz]?|swap|renomme[rz]?|rename|retitle|change[rz]?|modifie[rz]?|"
    r"remplace[rz]?|replace|ajoute[rz]?|ins[èe]re[rz]?|add|insert|touche[rz]?)\b",
    re.I,
)


def _unsure(text: str) -> bool:
    """A negation, contrast, question or hesitation, or more than one action: not for the words alone to apply."""
    bare = re.sub(r"[«\"“][^»\"”]*[»\"”]", " ", text)  # a new title in quotes is not an instruction
    return bool(_UNSURE.search(bare)) or len(_ACTION.findall(bare)) > 1


def direct_ops(words: str, doc: dict) -> tuple[list[dict], str] | None:
    """(operations, kind) when the user's words alone say what to change; None when the model must write it (and
    always on a negation, a contrast, a question, a hesitation or two actions: see ``_unsure``)."""
    text = (words or "").strip()
    if not text or len(text) > 240 or not doc or doc.get("kind") not in ("deck", "doc") or _unsure(text):
        return None
    ids = refs(text, doc)
    theme = _THEME_NAME.search(text)
    if _THEME_WORD.search(text) and (theme or re.search(r"\b(?:change|autre|another|different)", text, re.I)):
        if theme:
            return [{"op": "theme", "theme": dsl.theme_of(theme.group(1))}], "theme"
        order = list(dsl.THEMES)
        cur = doc.get("theme") if doc.get("theme") in order else "corporate"
        return [{"op": "theme", "theme": order[(order.index(cur) + 1) % len(order)]}], "theme"
    if not ids:
        return None
    if _IMAGE_WORD.search(text):
        if _DELETE.search(text) and not _REPLACE.search(text):
            return [{"op": "unimage", "id": i} for i in ids], "unimage"
        if _REPLACE.search(text) or _ADD_IMAGE.search(text):
            q = _image_query(text)
            return [{"op": "image", "id": i, "query": q, "again": not q} for i in ids], "image"
        return None
    if _SWAP.search(text) and len(ids) == 2:
        return [{"op": "swap", "id": ids[0], "other": ids[1]}], "swap"
    if _DELETE.search(text) and not re.search(r"\b(?:mots?|phrases?|lignes?|points?|puces?|words?|sentences?|bullets?|"
                                              r"lines?|chiffres?|ce qui|tout ce)\b", text, re.I):  # fmt: skip
        return [{"op": "delete", "id": i} for i in ids], "delete"
    if _DUP.search(text):
        return [{"op": "duplicate", "id": i} for i in ids], "duplicate"
    if _MOVE.search(text) and (
        len(ids) == 2
        or re.search(
            r"\b(?:au d[ée]but|en premier|at the start|first|"
            r"à la fin|en dernier|at the end|last)\b",
            text,
            re.I,
        )
    ):
        if re.search(
            r"\b(?:au d[ée]but|en premier|en premi[èe]re position|at the start|to the start|first)\b", text, re.I
        ):
            return [{"op": "move", "id": ids[0], "after": "start"}], "move"
        if re.search(r"\b(?:à la fin|a la fin|en dernier|at the end|to the end|last)\b", text, re.I):
            return [{"op": "move", "id": ids[0], "after": "end"}], "move"
        if len(ids) == 2:
            target = ids[1]
            if re.search(r"\b(?:avant|before)\b", text, re.I):
                j = _index(doc, target)
                after = doc["blocks"][j - 1]["id"] if j > 0 else "start"
                if after == ids[0]:
                    return None
                return [{"op": "move", "id": ids[0], "after": after}], "move"
            return [{"op": "move", "id": ids[0], "after": target}], "move"
    if _RENAME.search(text) and len(ids) == 1:
        m = re.search(r"\b(?:en|:|par|to|as)\s+[«\"“']?(?P<t>[^«»\"”']{2,120}?)[»\"”']?\s*$", text, re.I)
        if m:
            return [{"op": "retitle", "id": ids[0], "title": m.group("t").strip()}], "retitle"
    return None


# ------------------------------------------------------------------ what the model wrote

_OP = re.compile(
    r"^\s*@?\s*(?P<verb>replace|remplace[rz]?|modifie[rz]?|update|edit|r[ée][ée]cri[st]|rewrite|"
    r"insert[- ]?after|insert|ins[èe]re[rz]?(?: apr[èe]s)?|add[- ]?after|add|append|ajoute[rz]?(?: apr[èe]s)?|after|"
    r"apr[èe]s|before|avant|insert[- ]?before|start|d[ée]but|end|fin|delete|remove|supprime[rz]?|retire[rz]?|"
    r"move|d[ée]place[rz]?|theme|th[èe]me|title|titre)\b\s*:?\s*(?P<rest>.*)$",
    re.I,
)


def _verb(v: str) -> str:
    v = v.lower()
    if re.match(r"replace|remplace|modifie|update|edit|r[ée][ée]cri|rewrite", v):
        return "replace"
    if re.match(r"delete|remove|supprime|retire", v):
        return "delete"
    if re.match(r"move|d[ée]place", v):
        return "move"
    if re.match(r"theme|th[èe]me", v):
        return "theme"
    if re.match(r"title|titre", v):
        return "title"
    if re.match(r"before|avant|insert[- ]?before", v):
        return "before"
    if re.match(r"start|d[ée]but", v):
        return "start"
    if re.match(r"end|fin|append", v) or v in ("add", "ajoute", "ajouter", "ajoutez", "insert", "insère", "insere"):
        return "end"
    return "after"


def _is_op_line(line: str) -> re.Match | None:
    s = line.strip()
    if not s.startswith("@") and not re.match(r"^[A-Z]{3,}\b", s):
        return None  # without '@', only an all-caps verb line (REPLACE b3) is an operation, never prose
    return _OP.match(s.lstrip("@ "))


def _default_after(doc: dict, words: str) -> str:
    """Where a new block goes when nothing says: where the user said (« après la slide 3 », « au début »), else
    before a closing block (« Merci », « Questions », « Conclusion »), else at the end."""
    ids = refs(words, doc)
    if re.search(r"\b(?:au d[ée]but|en premier|at the start|at the beginning)\b", words or "", re.I):
        return "start"
    if ids and re.search(r"\b(?:apr[èe]s|after|suite [àa])\b", words or "", re.I):
        return ids[0]
    if ids and re.search(r"\b(?:avant|before)\b", words or "", re.I):
        j = _index(doc, ids[0])
        return doc["blocks"][j - 1]["id"] if j > 0 else "start"
    blocks = doc.get("blocks") or []
    if len(blocks) > 1 and re.match(r"(?i)^\s*(?:merci|thanks?|thank you|questions?|conclusion|contact|q ?& ?a|"
                                    r"prochaines? [ée]tapes|next steps)", blocks[-1].get("title") or ""):  # fmt: skip
        return blocks[-2]["id"]
    return "end"


def parse_patch(text: str, doc: dict, words: str = "", target: str | None = None,
                repairs: list[str] | None = None) -> tuple[list[dict], str]:  # fmt: skip
    """(operations, mode) from what the model wrote on a patch turn. mode: 'ops' (directives or tagged blocks),
    'rewrite' (the whole document again), 'insert' (new blocks placed by the harness), 'target' (the block the
    user pointed at in the canvas, rewritten), or 'none'."""
    repairs = repairs if repairs is not None else []
    src = str(text or "").replace("\r\n", "\n")
    if any(_is_op_line(ln) for ln in src.split("\n")):
        content = src  # « @replace b2 » before the first heading is an operation, not chat prose
    else:
        _, content, _ = dsl.split_answer(src)
    kind = doc.get("kind") or "deck"
    lines = content.split("\n")
    ops: list[dict] = []
    if target:
        new = dsl.parse(content, kind, doc.get("lang") or "fr", repairs)
        if new["blocks"]:
            first = new["blocks"][0]
            ops.append({"op": "replace", "id": target, "block": first})
            anchor = target
            for b in new["blocks"][1:]:
                ops.append({"op": "insert", "after": anchor, "block": b})
                anchor = "__last__"
            return _resolve_last(ops), "target"
        return [], "none"
    if any(_is_op_line(ln) for ln in lines):
        chunks: list[tuple[re.Match, list[str]]] = []
        for ln in lines:
            m = _is_op_line(ln)
            if m:
                chunks.append((m, []))
            elif chunks:
                chunks[-1][1].append(ln)
        for m, body in chunks:
            verb, rest = _verb(m.group("verb")), m.group("rest").strip()
            bid = re.search(r"\bb\d{1,3}\b", rest)
            bid_s = bid.group(0) if bid else None
            block_text = "\n".join(body)
            if verb == "theme":
                ops.append({"op": "theme", "theme": rest.split()[0] if rest else ""})
                continue
            if verb == "title":
                ops.append({"op": "meta", "title": rest.strip("\"'«» ")})
                continue
            if verb == "delete":
                for x in re.findall(r"\bb\d{1,3}\b", rest) or ([bid_s] if bid_s else []):
                    ops.append({"op": "delete", "id": x})
                continue
            if verb == "move":
                found = re.findall(r"\bb\d{1,3}\b", rest)
                if found:
                    after = (
                        found[1] if len(found) > 1 else ("start" if re.search(r"d[ée]but|start", rest, re.I) else "end")
                    )
                    if len(found) > 1 and re.search(r"\b(?:avant|before)\b", rest, re.I):
                        j = _index(doc, found[1])
                        after = doc["blocks"][j - 1]["id"] if j > 0 else "start"
                    ops.append({"op": "move", "id": found[0], "after": after})
                continue
            parsed = dsl.parse(block_text, kind, doc.get("lang") or "fr", repairs)["blocks"]
            if not parsed:
                repairs.append(f"operation {verb} without content ignored")
                continue
            if verb == "replace":
                target_id = bid_s or parsed[0].get("id")
                if _index(doc, target_id) < 0:
                    repairs.append(f"replace of unknown block {target_id}: inserted instead")
                    ops += [{"op": "insert", "after": _default_after(doc, words), "block": b} for b in parsed]
                    continue
                ops.append({"op": "replace", "id": target_id, "block": parsed[0]})
                anchor = target_id
                for b in parsed[1:]:
                    ops.append({"op": "insert", "after": anchor, "block": b})
                    anchor = "__last__"
                continue
            if verb == "start":
                after = "start"
            elif verb == "end":
                after = (
                    bid_s
                    if bid_s and re.search(r"apr[èe]s|after", m.group("verb") + rest, re.I)
                    else (_default_after(doc, words))
                )
            elif verb == "before":
                j = _index(doc, bid_s)
                after = doc["blocks"][j - 1]["id"] if j > 0 else "start"
            else:
                after = bid_s or _default_after(doc, words)
            for b in parsed:
                b.pop("id", None)
                ops.append({"op": "insert", "after": after, "block": b})
                after = "__last__"
        return _resolve_last(ops), "ops" if ops else "none"
    new = dsl.parse(content, kind, doc.get("lang") or "fr", repairs)
    blocks = new["blocks"]
    if not blocks:
        return [], "none"
    old = doc.get("blocks") or []
    old_ids = {b["id"] for b in old}
    tagged = [b for b in blocks if _tag_of(content, b) in old_ids]
    if tagged and len(blocks) < max(2, int(len(old) * 0.6)):
        # « # [b3] Les risques » : the model kept the id of the block it rewrote
        anchor = None
        for b in blocks:
            tid = _tag_of(content, b)
            if tid in old_ids:
                ops.append({"op": "replace", "id": tid, "block": b})
                anchor = tid
            else:
                ops.append({"op": "insert", "after": anchor or _default_after(doc, words), "block": b})
                anchor = "__last__"
        return _resolve_last(ops), "ops"
    if len(blocks) >= max(2, int(len(old) * 0.6)) or not old:
        return [{"op": "rewrite", "doc": new}], "rewrite"
    after = _default_after(doc, words)
    for b in blocks:
        ops.append({"op": "insert", "after": after, "block": b})
        after = "__last__"
    return _resolve_last(ops), "insert"


def _tag_of(content: str, block: dict) -> str | None:
    """The id tag the model left on this block's heading (the parser keeps it as the block id)."""
    return block.get("id") if re.search(rf"\[\s*{re.escape(str(block.get('id')))}\s*\]", content) else None


def _resolve_last(ops: list[dict]) -> list[dict]:
    """``after: '__last__'`` (right after the block inserted just before) is resolved when applied: see apply_all."""
    return ops


def apply_all(doc: dict, ops: list[dict]) -> tuple[dict, list[str], list[str]]:
    """``apply`` plus the two harness-only operations: 'rewrite' (a new version of the whole document, keeping
    the theme, the media and the ids of blocks whose title did not change) and inserts chained with '__last__'."""
    cur = dsl.clone(doc)
    done_all, failed_all = [], []
    last = None
    for op in ops:
        if op.get("op") == "rewrite":
            cur = rewrite(cur, op["doc"])
            done_all.append("rewrite")
            continue
        if op.get("after") == "__last__":
            op = {**op, "after": last or "end"}
        cur, done, failed = apply(cur, [op])
        done_all += done
        failed_all += failed
        if done and op.get("op") == "insert":
            last = done[-1].split()[-1]
        elif done and op.get("op") == "replace":
            last = op.get("id")
    return cur, done_all, failed_all


def rewrite(old: dict, new: dict) -> dict:
    """The new text of the whole document as the next version: the theme, subtitle and pictures already chosen
    are kept unless the model changed them, and a block keeps its id when its title is the same."""
    out = dsl.clone(old)
    out["title"] = new.get("title") or old.get("title") or ""
    out["subtitle"] = new.get("subtitle") or old.get("subtitle") or ""
    out["theme"] = new.get("theme") or old.get("theme")
    by_title = {re.sub(r"\W+", " ", (b.get("title") or "").lower()).strip(): b for b in old.get("blocks") or []}
    blocks = []
    used: set[str] = set()
    for b in new.get("blocks") or []:
        key = re.sub(r"\W+", " ", (b.get("title") or "").lower()).strip()
        prev = by_title.get(key)
        nb = {"id": "", "title": b.get("title") or "", "parts": b.get("parts") or [], "notes": b.get("notes") or ""}
        if prev and prev["id"] not in used:
            nb["id"] = prev["id"]
            used.add(prev["id"])
            # the picture already found for this block stays (same query), so a rewrite does not search again
            old_img = next((p for p in prev.get("parts") or [] if p.get("t") == "image" and p.get("media")), None)
            for p in nb["parts"]:
                if p.get("t") == "image" and old_img and p.get("query") == old_img.get("query"):
                    p["media"] = old_img["media"]
        blocks.append(nb)
    nxt = max([int(old.get("_next") or 1)] + [int(b["id"][1:]) + 1 for b in old.get("blocks") or []])
    for nb in blocks:
        if not nb["id"]:
            nb["id"], nxt = f"b{nxt}", nxt + 1
    out["blocks"], out["_next"] = blocks, nxt
    return out
