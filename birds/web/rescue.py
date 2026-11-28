"""Rich results that do not depend on the model.

A pre-called tool (a map, a company record, a rate, a forecast) is the harness's work, not the model's. So:

- ``step_widgets``: the card of a finished step, sent to the page at once (the ``widget`` event), before the model
  writes anything; the page keeps it in the turn whatever happens next;
- ``summary_text``: when the model then fails (endpoint in error, out of time, empty output), a short answer written
  from the cards alone (« Voici 8 restaurants autour de Gare de Lyon. »), shown with a discreet note instead of an
  error card. Facts of the cards only: nothing is guessed.
"""

from __future__ import annotations

import re

from .widgets import build_widgets

# the run ended without an answer of the model's own
NO_ANSWER = {"timeout", "max_steps", "invalid_tool_calls", "loop", "empty_output", "malformed_output"}

_FR = {
    "restaurant": ("restaurant", "restaurants"), "cafe": ("café", "cafés"), "bar": ("bar", "bars"),
    "hotel": ("hôtel", "hôtels"), "pharmacy": ("pharmacie", "pharmacies"), "parking": ("parking", "parkings"),
    "bank": ("banque", "banques"), "atm": ("distributeur", "distributeurs"),
    "supermarket": ("supermarché", "supermarchés"), "fuel": ("station-service", "stations-service"),
    "car_repair": ("garage", "garages"), "bakery": ("boulangerie", "boulangeries"),
    "charging station": ("borne de recharge", "bornes de recharge"), "coworking": ("coworking", "coworkings"),
    "conference centre": ("salle de réunion", "salles de réunion"),
    "post office": ("bureau de poste", "bureaux de poste"), "train station": ("gare", "gares"),
    "subway station": ("station de métro", "stations de métro"), "hospital": ("hôpital", "hôpitaux"),
    "doctors": ("médecin", "médecins"), "copyshop": ("imprimerie", "imprimeries"),
    "bookshop": ("librairie", "librairies"), "museum": ("musée", "musées"), "cinema": ("cinéma", "cinémas"),
    "fitness centre": ("salle de sport", "salles de sport"), "kindergarten": ("crèche", "crèches"),
    "school": ("école", "écoles"), "pizza": ("pizzeria", "pizzerias"), "florist": ("fleuriste", "fleuristes"),
    "laundry": ("laverie", "laveries"),
}  # fmt: skip
_EN = {
    "cafe": ("café", "cafés"), "atm": ("cash machine", "cash machines"), "pizza": ("pizzeria", "pizzerias"),
    "car_repair": ("garage", "garages"), "fuel": ("petrol station", "petrol stations"),
    "copyshop": ("print shop", "print shops"), "laundry": ("laundrette", "laundrettes"),
    "doctors": ("doctor", "doctors"), "kindergarten": ("nursery", "nurseries"),
    "conference centre": ("meeting room", "meeting rooms"), "charging station": ("charging station", "charging stations"),
}  # fmt: skip
NOTE = {
    "fr": "Réponse rédigée automatiquement à partir des résultats ci-dessous.",
    "en": "Answer written automatically from the results below.",
}


def step_widgets(step, lang: str, secret: bytes, layer: str = "osm", geo_on: bool = True) -> list[dict]:
    """The card(s) of one finished tool step, built exactly as the final answer builds them."""
    if getattr(step, "error", None) or not isinstance((getattr(step, "info", None) or {}).get("widget"), dict):
        return []
    try:
        return build_widgets([step], "", lang, None, secret, layer=layer, geo_on=geo_on)
    except Exception:  # noqa: BLE001 - a widget bug never breaks the run
        return []


def _km(m, lang: str) -> str:
    if m is None:
        return ""
    if m < 1000:
        return f"{m} m"
    km = f"{m / 1000:.1f}"
    return (km.replace(".", ",") if lang == "fr" else km) + " km"


def _kinds(kind: str, n: int, lang: str) -> str:
    if lang == "fr":
        one, many = _FR.get(kind, ("lieu", "lieux"))
    else:
        one, many = _EN.get(kind, (kind or "place", f"{kind}s" if kind else "places"))
    return f"{n} {one if n == 1 else many}"


def places_lines(w: dict, lang: str) -> list[str]:
    fr = lang != "en"
    ps, mode = w.get("places") or [], w.get("mode")
    if not ps:
        return []
    if mode == "near" and w.get("center"):
        what, near = _kinds(str(w.get("query") or ""), len(ps), lang), w["center"]["name"]
        return [f"Voici {what} autour de {near}, du plus proche au plus loin." if fr
                else f"Here are {what} around {near}, nearest first."]  # fmt: skip
    if mode == "route" and len(ps) >= 2:
        d = _km(w.get("distance_m"), lang)
        return [f"{ps[0]['name']} et {ps[1]['name']} sont à {d} à vol d'oiseau ; le lien « Itinéraire » donne la route."
                if fr else f"{ps[0]['name']} and {ps[1]['name']} are {d} apart as the crow flies; the 'Directions' "
                "link gives the road route."]  # fmt: skip
    if mode == "list":
        n, miss = len(ps), w.get("missing") or []
        if w.get("plan") == "order" and w.get("order"):
            seq, total = " → ".join(str(x) for x in w["order"]), _km(w.get("total_m"), lang)
            out = [f"Voici les {n} lieux sur la carte. Ordre de visite le plus court à vol d'oiseau : {seq} ({total})."
                   if fr else f"Here are the {n} places on the map. Shortest visit order as the crow flies: {seq} "
                   f"({total})."]  # fmt: skip
        else:
            out = [f"Voici les {n} lieux sur la carte, dans l'ordre donné." if fr
                   else f"Here are the {n} places on the map, in the order given."]  # fmt: skip
        if miss:
            s = "s" if len(miss) > 1 else ""
            out.append((f"{len(miss)} adresse{s} introuvable{s} : " if fr else f"{len(miss)} not found: ")
                       + " ; ".join(miss) + ".")  # fmt: skip
        if hidden := w.get("not_shown") or []:
            s = "s" if len(hidden) > 1 else ""
            out.append((f"{len(hidden)} lieu{'x' if s else ''} non affiché{s} sur cette carte : "
                        if fr else f"{len(hidden)} not shown on this map: ")
                       + " ; ".join(hidden) + ".")  # fmt: skip
        if unchecked := w.get("unchecked") or []:
            s = "s" if len(unchecked) > 1 else ""
            out.append((f"{len(unchecked)} lieu{'x' if s else ''} non vérifié{s} (service de cartes indisponible) : "
                        if fr else f"{len(unchecked)} not checked (map service unavailable): ")
                       + " ; ".join(unchecked) + ".")  # fmt: skip
        return out
    p = ps[0]
    where = f" : {p['address']}" if p.get("address") and p["address"] != p["name"] else ""
    return [f"Voici où se trouve {p['name']}{where}." if fr else f"Here is where {p['name']} is{where}."]


def summary_text(widgets: list[dict], lang: str) -> str:
    """A short answer from the cards alone, or '' when no card can carry one."""
    fr = lang != "en"
    out: list[str] = []
    for w in widgets or []:
        t = w.get("type")
        if t == "places":
            out += places_lines(w, lang)
        elif t == "company" and w.get("name"):
            bits = [w["name"], f"SIREN {w['siren']}" if w.get("siren") else "", w.get("address") or ""]
            out.append(("Voici la fiche de l'entreprise : " if fr else "Here is the company record: ")
                       + " — ".join(b for b in bits if b) + ".")  # fmt: skip
        elif t == "fx" and w.get("result") is not None:
            when = (f" (taux BCE du {w['date']})" if fr else f" (ECB rate of {w['date']})") if w.get("date") else ""
            out.append(f"{w.get('amount')} {w.get('from')} = {w.get('result')} {w.get('to')}{when}.")
        elif t == "weather" and (w.get("place") or {}).get("name"):
            s, name = w.get("summary") or {}, w["place"]["name"]
            temp = ""
            if s.get("min") is not None and s.get("max") is not None:
                temp = f", {s['min']} à {s['max']} °C" if fr else f", {s['min']} to {s['max']} °C"
            label = str(s.get("label") or "").lower()
            out.append((f"Prévisions pour {name} : " if fr else f"Forecast for {name}: ") + f"{label}{temp}.")
    return " ".join(x for x in out if x)


# ---------------------------------------------------------------- the answer of a places turn, checked
# An answer that gives up (« je n'ai pas trouvé », « demandez à un voisin ») while the tool found places, or that names
# none of them, contradicts the card under it (production, 28/11/2026). The harness then writes the answer from the
# tool's results, never from the model's text.
GIVE_UP = re.compile(
    r"\bje n['’]ai (?:pas|rien) trouv|\baucune? (?:information|donn[ée]e|r[ée]sultat)s? fiables?|\bje ne (?:trouve|peux)"
    r" (?:pas|rien)|\bje ne suis pas en mesure|\bdemande[rz]? (?:à|a) (?:un |une |vos? |votre )?(?:voisin|passant|"
    r"habitant|accueil|médecin)|\bv[ée]rifie[rz]? sur (?:une|la) carte|\baucune? \w+ (?:n['’]est|ne figure|"
    r"n['’]appara[iî]t)|\bI (?:could not|couldn['’]t|did not|didn['’]t|cannot|can['’]t) find|\bask (?:a|your) "
    r"neighbo",
    re.I,
)


def _fold(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "").casefold().replace("’", "'"))
    return "".join(c for c in t if not unicodedata.combining(c))


def places_answer(widgets: list[dict], lang: str, caveat: str = "", n: int = 5) -> str:
    """The answer written from a near card: the nearest places, each with its address, distance and hours."""
    fr = lang != "en"
    w = next((x for x in widgets or [] if x.get("type") == "places" and x.get("mode") == "near" and x.get("places")),
             None)  # fmt: skip
    if w is None:
        return summary_text(widgets, lang)
    lines = places_lines(w, lang)
    for i, p in enumerate(w["places"][:n], 1):
        bits = [f"**{p['name']}**", p.get("address") or "", _km(p.get("distance_m"), lang)]
        if p.get("hours"):
            bits.append(("horaires : " if fr else "hours: ") + p["hours"])
        lines.append(f"{i}. " + " — ".join(b for b in bits if b))
    if caveat_line := _caveat_for_user(caveat, lang):
        lines.append(caveat_line)
    lines.append("La carte les situe ; le lien « Itinéraire » de chaque fiche calcule le trajet." if fr
                 else "The map shows them; each card's 'Directions' link computes the route.")  # fmt: skip
    return "\n".join(lines)


def _caveat_for_user(caveat: str, lang: str) -> str:
    """The qualifier OSM cannot check, said to the user (the tool told the model)."""
    if "3237" in caveat:
        return ("Pour la pharmacie de garde de nuit ou du dimanche : le 3237 ou 3237.fr." if lang != "en"
                else "For the night or Sunday duty pharmacy in France: 3237 or 3237.fr.")  # fmt: skip
    return ""


SEND_AWAY = re.compile(
    r"\bdemande[rz]? (?:à|a) (?:un |une |vos? |votre |l['’])?(?:voisin|passant|habitant|accueil|médecin)|"
    r"\bv[ée]rifie[rz]? (?:sur (?:une|la) carte|le site|aupr[èe]s)|\bask (?:a|your) neighbo|\bcheck a local map",
    re.I,
)


def _searched_nothing(steps, lang: str) -> str:
    """What Bird did when the category was found nowhere near the anchor, and the next step it offers."""
    info = next(((getattr(s, "info", None) or {}) for s in steps or [] if getattr(s, "tool", "") == "find_places"
                 and (getattr(s, "info", None) or {}).get("searched")), None)  # fmt: skip
    if not info:
        return ""
    got = info["searched"]
    fr = lang != "en"
    what = _kinds(str(got.get("query") or ""), 2, lang).split(" ", 1)[1]
    km = _km(got.get("radius_m"), lang)
    return (f"J'ai cherché les {what} sur OpenStreetMap dans un rayon de {km} autour de {got.get('near')} : aucun "
            "n'y est encore répertorié. Je peux élargir la zone, partir d'une adresse précise ou chercher une enseigne "
            "par son nom." if fr else
            f"I searched OpenStreetMap for {what} within {km} of {got.get('near')}: none is listed there yet. I can "
            "widen the area, start from a precise address or look up a brand by name.")  # fmt: skip


def check_places_answer(content: str, widgets: list[dict], steps, lang: str) -> str | None:
    """The answer rewritten from the places found when the model's answer contradicts them (gives up, or names none
    of the places of a near card), else None (the model's answer stands). Nothing found: an answer that sends the
    user elsewhere (« demandez à un voisin ») says instead what Bird searched and offers the next step."""
    cards = [w for w in widgets or [] if w.get("type") == "places" and w.get("places")]
    if not content:
        return None
    if not cards:
        return (_searched_nothing(steps, lang) or None) if SEND_AWAY.search(content) else None
    text = _fold(content)
    names = [_fold(p.get("name")) for w in cards for p in w["places"] if p.get("name")]
    named = any(nm and len(nm) >= 3 and nm in text for nm in names)
    near = any(w.get("mode") == "near" for w in cards)
    if not GIVE_UP.search(content) and (named or not near):
        return None
    caveat = next((str((getattr(s, "info", None) or {}).get("caveat") or "") for s in steps or []
                   if getattr(s, "tool", "") == "find_places" and (getattr(s, "info", None) or {}).get("caveat")), "")
    return places_answer(cards, lang, caveat) or None
