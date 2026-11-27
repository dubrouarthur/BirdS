"""French départements and régions (official INSEE codes, 2016 regions), for BOAMP filters and commune cards.

Pure data: ``where(text)`` reads « dans le 59 », « dans le Nord », « en Bretagne », « Hauts-de-France » into a label
and the list of département codes.
"""

from __future__ import annotations

import re

from .countries import fold

DEPARTMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme",
    "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire", "38": "Isère",
    "39": "Jura", "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche",
    "51": "Marne", "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise", "61": "Orne",
    "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées",
    "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie", "75": "Paris",
    "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme",
    "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne",
    "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
}  # fmt: skip
REGIONS = {
    "Auvergne-Rhône-Alpes": "01 03 07 15 26 38 42 43 63 69 73 74",
    "Bourgogne-Franche-Comté": "21 25 39 58 70 71 89 90",
    "Bretagne": "22 29 35 56",
    "Centre-Val de Loire": "18 28 36 37 41 45",
    "Corse": "2A 2B",
    "Grand Est": "08 10 51 52 54 55 57 67 68 88",
    "Hauts-de-France": "02 59 60 62 80",
    "Île-de-France": "75 77 78 91 92 93 94 95",
    "Normandie": "14 27 50 61 76",
    "Nouvelle-Aquitaine": "16 17 19 23 24 33 40 47 64 79 86 87",
    "Occitanie": "09 11 12 30 31 32 34 46 48 65 66 81 82",
    "Pays de la Loire": "44 49 53 72 85",
    "Provence-Alpes-Côte d'Azur": "04 05 06 13 83 84",
}
REGION_WORDS = {
    **{fold(k): k for k in REGIONS},
    "auvergne": "Auvergne-Rhône-Alpes", "rhone-alpes": "Auvergne-Rhône-Alpes", "aura": "Auvergne-Rhône-Alpes",
    "bourgogne": "Bourgogne-Franche-Comté", "franche-comte": "Bourgogne-Franche-Comté",
    "centre-val-de-loire": "Centre-Val de Loire", "alsace": "Grand Est", "lorraine": "Grand Est",
    "champagne-ardenne": "Grand Est", "picardie": "Hauts-de-France", "nord-pas-de-calais": "Hauts-de-France",
    "ile de france": "Île-de-France", "idf": "Île-de-France", "region parisienne": "Île-de-France",
    "aquitaine": "Nouvelle-Aquitaine", "limousin": "Nouvelle-Aquitaine", "poitou-charentes": "Nouvelle-Aquitaine",
    "languedoc": "Occitanie", "midi-pyrenees": "Occitanie", "paca": "Provence-Alpes-Côte d'Azur",
    "provence": "Provence-Alpes-Côte d'Azur", "cote d'azur": "Provence-Alpes-Côte d'Azur",
}  # fmt: skip
_DEP_WORDS = {fold(v): k for k, v in DEPARTMENTS.items()}
_DEP_WORDS.pop("paris", None)  # « à Paris » is the city: kept, as the département 75 below
_DEP_WORDS.update({"paris": "75", "la reunion": "974", "reunion": "974"})

_RX_CODE = re.compile(r"(?:\bdans\s+le|\ben|\bdu|\bin|\bdepartement|\bd[ée]p\.?|\(|^)\s*(2[AB]|97[1-6]|\d{2})\b(?!\s*(?:%|€|k|m|jours?|ans?|h\b|mois|lots?))", re.I)  # fmt: skip


def where(text: str) -> tuple[str, list[str]]:
    """(label, département codes) for the place a request names, or ('', [])."""
    t = fold(text)
    for w in sorted(REGION_WORDS, key=len, reverse=True):
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", t):
            name = REGION_WORDS[w]
            return name, REGIONS[name].split()
    m = _RX_CODE.search(text or "")
    if m:
        code = m.group(1).upper().zfill(2)
        if code in DEPARTMENTS:
            return f"{DEPARTMENTS[code]} ({code})", [code]
    for w in sorted(_DEP_WORDS, key=len, reverse=True):
        # « Var », « Lot », « Cher », « Ain »: ordinary words too, so only after « dans le » or « département du »
        lead = (r"(?:\bdans\s+(?:le|la|les|l')\s*|\bd[ée]partement\s+(?:du|de\s+la|de\s+l'|des)\s*)" if len(w) <= 5
                else r"(?:\b(?:dans\s+(?:le|la|les|l')|en|du|de\s+la|des|dans|in)\s*)")
        if len(w) >= 3 and re.search(lead + re.escape(w) + r"(?![\w-])", t):
            code = _DEP_WORDS[w]
            return f"{DEPARTMENTS[code]} ({code})", [code]
    return "", []
