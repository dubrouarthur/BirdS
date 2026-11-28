"""Countries and aggregates the open-data tools name: FR/EN names, adjectives, ISO codes, Eurostat codes.

Pure data. ``find(text)`` returns the countries written in a text, in order (« la France et l'Allemagne »,
« PIB du Maroc vs Tunisie », « French GDP »). Eurostat writes Greece EL and the United Kingdom UK.
"""

from __future__ import annotations

import re
import unicodedata

# iso2: (french name, english name, iso3, words written by users (folded: lower case, no accent))
COUNTRIES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "FR": ("France", "France", "FRA", ("france", "francais", "francaise", "french", "hexagone")),
    "DE": ("Allemagne", "Germany", "DEU", ("allemagne", "allemand", "allemande", "germany", "german")),
    "ES": ("Espagne", "Spain", "ESP", ("espagne", "espagnol", "espagnole", "spain", "spanish")),
    "IT": ("Italie", "Italy", "ITA", ("italie", "italien", "italienne", "italy", "italian")),
    "PT": ("Portugal", "Portugal", "PRT", ("portugal", "portugais", "portugaise", "portuguese")),
    "BE": ("Belgique", "Belgium", "BEL", ("belgique", "belge", "belgium", "belgian")),
    "NL": ("Pays-Bas", "Netherlands", "NLD", ("pays-bas", "pays bas", "neerlandais", "netherlands", "dutch",
                                              "hollande")),
    "LU": ("Luxembourg", "Luxembourg", "LUX", ("luxembourg", "luxembourgeois")),
    "IE": ("Irlande", "Ireland", "IRL", ("irlande", "irlandais", "ireland", "irish")),
    "AT": ("Autriche", "Austria", "AUT", ("autriche", "autrichien", "austria", "austrian")),
    "CH": ("Suisse", "Switzerland", "CHE", ("suisse", "switzerland", "swiss")),
    "GB": ("Royaume-Uni", "United Kingdom", "GBR", ("royaume-uni", "royaume uni", "britannique", "united kingdom",
                                                    "uk", "britain", "british", "angleterre", "england")),
    "PL": ("Pologne", "Poland", "POL", ("pologne", "polonais", "poland", "polish")),
    "SE": ("Suède", "Sweden", "SWE", ("suede", "suedois", "sweden", "swedish")),
    "DK": ("Danemark", "Denmark", "DNK", ("danemark", "danois", "denmark", "danish")),
    "FI": ("Finlande", "Finland", "FIN", ("finlande", "finlandais", "finland", "finnish")),
    "NO": ("Norvège", "Norway", "NOR", ("norvege", "norvegien", "norway", "norwegian")),
    "IS": ("Islande", "Iceland", "ISL", ("islande", "iceland")),
    "GR": ("Grèce", "Greece", "GRC", ("grece", "grec", "grecque", "greece", "greek")),
    "CZ": ("Tchéquie", "Czechia", "CZE", ("tchequie", "republique tcheque", "tcheque", "czechia", "czech republic")),
    "SK": ("Slovaquie", "Slovakia", "SVK", ("slovaquie", "slovakia")),
    "HU": ("Hongrie", "Hungary", "HUN", ("hongrie", "hongrois", "hungary", "hungarian")),
    "RO": ("Roumanie", "Romania", "ROU", ("roumanie", "roumain", "romania", "romanian")),
    "BG": ("Bulgarie", "Bulgaria", "BGR", ("bulgarie", "bulgaria")),
    "HR": ("Croatie", "Croatia", "HRV", ("croatie", "croatia")),
    "SI": ("Slovénie", "Slovenia", "SVN", ("slovenie", "slovenia")),
    "EE": ("Estonie", "Estonia", "EST", ("estonie", "estonia")),
    "LV": ("Lettonie", "Latvia", "LVA", ("lettonie", "latvia")),
    "LT": ("Lituanie", "Lithuania", "LTU", ("lituanie", "lithuania")),
    "CY": ("Chypre", "Cyprus", "CYP", ("chypre", "cyprus")),
    "MT": ("Malte", "Malta", "MLT", ("malte", "malta")),
    "TR": ("Turquie", "Türkiye", "TUR", ("turquie", "turc", "turkey", "turkiye", "turkish")),
    "US": ("États-Unis", "United States", "USA", ("etats-unis", "etats unis", "usa", "united states",
                                                 "americain", "americaine", "american", "amerique")),
    "CA": ("Canada", "Canada", "CAN", ("canada", "canadien", "canadian")),
    "MX": ("Mexique", "Mexico", "MEX", ("mexique", "mexico", "mexicain")),
    "BR": ("Brésil", "Brazil", "BRA", ("bresil", "bresilien", "brazil", "brazilian")),
    "AR": ("Argentine", "Argentina", "ARG", ("argentine", "argentina")),
    "CL": ("Chili", "Chile", "CHL", ("chili", "chile")),
    "CO": ("Colombie", "Colombia", "COL", ("colombie", "colombia")),
    "PE": ("Pérou", "Peru", "PER", ("perou", "peru")),
    "MA": ("Maroc", "Morocco", "MAR", ("maroc", "marocain", "morocco", "moroccan")),
    "DZ": ("Algérie", "Algeria", "DZA", ("algerie", "algerien", "algeria")),
    "TN": ("Tunisie", "Tunisia", "TUN", ("tunisie", "tunisien", "tunisia")),
    "EG": ("Égypte", "Egypt", "EGY", ("egypte", "egypt")),
    "SN": ("Sénégal", "Senegal", "SEN", ("senegal",)),
    "CI": ("Côte d'Ivoire", "Côte d'Ivoire", "CIV", ("cote d'ivoire", "cote divoire", "ivory coast")),
    "CM": ("Cameroun", "Cameroon", "CMR", ("cameroun", "cameroon")),
    "NG": ("Nigeria", "Nigeria", "NGA", ("nigeria",)),
    "ZA": ("Afrique du Sud", "South Africa", "ZAF", ("afrique du sud", "south africa")),
    "KE": ("Kenya", "Kenya", "KEN", ("kenya",)),
    "CN": ("Chine", "China", "CHN", ("chine", "chinois", "china", "chinese")),
    "JP": ("Japon", "Japan", "JPN", ("japon", "japonais", "japan", "japanese")),
    "KR": ("Corée du Sud", "South Korea", "KOR", ("coree du sud", "coree", "south korea", "korea")),
    "IN": ("Inde", "India", "IND", ("inde", "indien", "india", "indian")),
    "VN": ("Vietnam", "Viet Nam", "VNM", ("vietnam", "viet nam", "vietnamien")),
    "TH": ("Thaïlande", "Thailand", "THA", ("thailande", "thailand")),
    "ID": ("Indonésie", "Indonesia", "IDN", ("indonesie", "indonesia")),
    "MY": ("Malaisie", "Malaysia", "MYS", ("malaisie", "malaysia")),
    "SG": ("Singapour", "Singapore", "SGP", ("singapour", "singapore")),
    "PH": ("Philippines", "Philippines", "PHL", ("philippines",)),
    "AU": ("Australie", "Australia", "AUS", ("australie", "australien", "australia", "australian")),
    "NZ": ("Nouvelle-Zélande", "New Zealand", "NZL", ("nouvelle-zelande", "nouvelle zelande", "new zealand")),
    "RU": ("Russie", "Russia", "RUS", ("russie", "russe", "russia", "russian")),
    "UA": ("Ukraine", "Ukraine", "UKR", ("ukraine",)),
    "IL": ("Israël", "Israel", "ISR", ("israel",)),
    "SA": ("Arabie saoudite", "Saudi Arabia", "SAU", ("arabie saoudite", "saudi arabia")),
    "AE": ("Émirats arabes unis", "United Arab Emirates", "ARE", ("emirats arabes unis", "emirats", "uae",
                                                                 "united arab emirates")),
    "QA": ("Qatar", "Qatar", "QAT", ("qatar",)),
}  # fmt: skip
# aggregates: code -> (fr, en, eurostat code or "", world bank code or "", words)
AGGREGATES: dict[str, tuple[str, str, str, str, tuple[str, ...]]] = {
    "EA": ("Zone euro", "Euro area", "EA", "EMU", ("zone euro", "eurozone", "euro area", "euro zone")),
    "EU": ("Union européenne", "European Union", "EU27_2020", "EUU", ("union europeenne", "ue", "eu",
                                                                     "european union", "l'europe", "europe")),
    "WLD": ("Monde", "World", "", "WLD", ("monde", "mondial", "world", "worldwide")),
}  # fmt: skip
EU27 = set("AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split())
# Eurostat's labour-force and price tables also cover these
EUROSTAT_EXTRA = {"NO", "IS", "CH", "TR"}


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("’", "'").split())


_WORDS = sorted(
    [(w, cc) for cc, (*_, words) in COUNTRIES.items() for w in words]
    + [(w, code) for code, (*_, words) in AGGREGATES.items() for w in words],
    key=lambda x: -len(x[0]),
)
_RX = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w, _ in _WORDS) + r")(?![\w-])")
_BY_WORD = dict(_WORDS)
# words that are a country only with a capital letter or a preposition (« les US », « en UE » are rare in office
# text; « us » and « eu » are ordinary English words)
_AMBIGUOUS = {"us", "eu", "ue", "uk", "europe", "l'europe", "inde", "chine", "turc", "grec", "chili", "coree"}


def find(text: str) -> list[str]:
    """ISO2 codes (or EA / EU / WLD) written in ``text``, in order, without repeats."""
    raw = str(text or "")
    t = fold(raw)
    out: list[str] = []
    for m in _RX.finditer(t):
        w = m.group(1)
        if w in ("us", "eu", "uk"):
            # only the capitalised acronym (« les US », « UK GDP »), never « tell us », « eu » (portuguese)
            if not re.search(r"(?<![\w-])" + w.upper() + r"(?![\w-])", raw):
                continue
        if w == "ue" and not re.search(r"(?<![\w-])UE(?![\w-])", raw):
            continue
        code = _BY_WORD[w]
        if code not in out:
            out.append(code)
    return out


def name(code: str, lang: str) -> str:
    if code in COUNTRIES:
        return COUNTRIES[code][0 if lang == "fr" else 1]
    if code in AGGREGATES:
        return AGGREGATES[code][0 if lang == "fr" else 1]
    return code


def eurostat_code(code: str) -> str:
    if code in AGGREGATES:
        return AGGREGATES[code][2]
    return {"GR": "EL", "GB": "UK"}.get(code, code)


def worldbank_code(code: str) -> str:
    if code in AGGREGATES:
        return AGGREGATES[code][3]
    return COUNTRIES[code][2] if code in COUNTRIES else ""


def in_eurostat(code: str) -> bool:
    return code in EU27 or code in EUROSTAT_EXTRA or code in ("EA", "EU")
