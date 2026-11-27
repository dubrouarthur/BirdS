"""Rich results that do not depend on the model.

A pre-called tool (a map, a company record, a rate, a forecast) is the harness's work, not the model's. So:

- ``step_widgets``: the card of a finished step, sent to the page at once (the ``widget`` event), before the model
  writes anything; the page keeps it in the turn whatever happens next;
- ``summary_text``: when the model then fails (endpoint in error, out of time, empty output), a short answer written
  from the cards alone (« Voici 8 restaurants autour de Gare de Lyon. »), shown with a discreet note instead of an
  error card. Facts of the cards only: nothing is guessed.
"""

from __future__ import annotations

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
