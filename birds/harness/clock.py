"""World clock and common meeting slot, from the user's own words. No tool, no network, no model for the numbers.

« quelle heure est-il à New York », « décalage horaire avec Tokyo », « trouve un créneau commun Paris Montréal
Singapour » -> ``detect`` finds the ask and the cities (a built-in city -> IANA zone table, FR/EN names, plus a
few countries by their capital); ``card`` computes each city's local time and, for 2 to 4 zones, a 24-column day of
office hours (9-18 local, Monday to Friday) in the user's zone with the common slot(s). The harness gives the model
``summary`` (a compact note) and the UI the card. A zone always comes from this table, never from coordinates: a
geocoder may only tell which country an unknown town is in (``zone_for_country``). Pure: see tests/test_clock.py.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

try:  # the zone database shipped as a package: serverless hosts may have no /usr/share/zoneinfo
    import tzdata  # noqa: F401
except ImportError:  # pragma: no cover - zoneinfo then uses the system database
    tzdata = None

OFFICE = (9 * 60, 18 * 60)  # minutes, local time, Monday to Friday
WIDE = (7 * 60, 21 * 60)  # the compromise when no office slot is shared: early or late for someone, said so
STEP = 15  # minutes: half-hour and 45-minute zones (India, Nepal, Newfoundland) are exact
MAX_CITIES = 4
DEFAULT_TZ = "Europe/Paris"

# name FR | name EN | IANA zone | ISO country | other spellings (comma separated). Capitals first in each region.
_TABLE = """
Paris|Paris|Europe/Paris|FR|
Saint-Denis|Saint-Denis|Europe/Paris|FR|st-denis,st denis
Lyon|Lyon|Europe/Paris|FR|
Marseille|Marseille|Europe/Paris|FR|
Toulouse|Toulouse|Europe/Paris|FR|
Nice|Nice|Europe/Paris|FR|
Nantes|Nantes|Europe/Paris|FR|
Strasbourg|Strasbourg|Europe/Paris|FR|
Montpellier|Montpellier|Europe/Paris|FR|
Bordeaux|Bordeaux|Europe/Paris|FR|
Lille|Lille|Europe/Paris|FR|
Rennes|Rennes|Europe/Paris|FR|
Grenoble|Grenoble|Europe/Paris|FR|
Londres|London|Europe/London|GB|
Manchester|Manchester|Europe/London|GB|
Édimbourg|Edinburgh|Europe/London|GB|edimbourg
Dublin|Dublin|Europe/Dublin|IE|
Bruxelles|Brussels|Europe/Brussels|BE|
Anvers|Antwerp|Europe/Brussels|BE|antwerpen
Amsterdam|Amsterdam|Europe/Amsterdam|NL|
Rotterdam|Rotterdam|Europe/Amsterdam|NL|
La Haye|The Hague|Europe/Amsterdam|NL|den haag
Luxembourg|Luxembourg|Europe/Luxembourg|LU|
Berne|Bern|Europe/Zurich|CH|
Genève|Geneva|Europe/Zurich|CH|geneve,genf
Zurich|Zurich|Europe/Zurich|CH|zürich
Lausanne|Lausanne|Europe/Zurich|CH|
Berlin|Berlin|Europe/Berlin|DE|
Munich|Munich|Europe/Berlin|DE|münchen,munchen
Francfort|Frankfurt|Europe/Berlin|DE|frankfurt am main
Hambourg|Hamburg|Europe/Berlin|DE|
Cologne|Cologne|Europe/Berlin|DE|köln,koln
Vienne (Autriche)|Vienna|Europe/Vienna|AT|vienna,wien
Madrid|Madrid|Europe/Madrid|ES|
Barcelone|Barcelona|Europe/Madrid|ES|barcelona
Séville|Seville|Europe/Madrid|ES|sevilla,seville
Lisbonne|Lisbon|Europe/Lisbon|PT|lisboa
Porto|Porto|Europe/Lisbon|PT|
Rome|Rome|Europe/Rome|IT|roma
Milan|Milan|Europe/Rome|IT|milano
Naples|Naples|Europe/Rome|IT|napoli
Turin|Turin|Europe/Rome|IT|torino
Florence|Florence|Europe/Rome|IT|firenze
Venise|Venice|Europe/Rome|IT|venezia
Athènes|Athens|Europe/Athens|GR|athenes
Copenhague|Copenhagen|Europe/Copenhagen|DK|københavn
Stockholm|Stockholm|Europe/Stockholm|SE|
Oslo|Oslo|Europe/Oslo|NO|
Helsinki|Helsinki|Europe/Helsinki|FI|
Reykjavik|Reykjavik|Atlantic/Reykjavik|IS|reykjavík
Varsovie|Warsaw|Europe/Warsaw|PL|warszawa
Cracovie|Krakow|Europe/Warsaw|PL|kraków,cracow
Prague|Prague|Europe/Prague|CZ|praha
Budapest|Budapest|Europe/Budapest|HU|
Bratislava|Bratislava|Europe/Bratislava|SK|
Ljubljana|Ljubljana|Europe/Ljubljana|SI|
Zagreb|Zagreb|Europe/Zagreb|HR|
Belgrade|Belgrade|Europe/Belgrade|RS|beograd
Sarajevo|Sarajevo|Europe/Sarajevo|BA|
Podgorica|Podgorica|Europe/Podgorica|ME|
Skopje|Skopje|Europe/Skopje|MK|
Tirana|Tirana|Europe/Tirane|AL|tirane
Sofia|Sofia|Europe/Sofia|BG|
Bucarest|Bucharest|Europe/Bucharest|RO|bucuresti
Chișinău|Chisinau|Europe/Chisinau|MD|chisinau,kichinev
Kyiv|Kyiv|Europe/Kyiv|UA|kiev,kiew
Minsk|Minsk|Europe/Minsk|BY|
Vilnius|Vilnius|Europe/Vilnius|LT|
Riga|Riga|Europe/Riga|LV|
Tallinn|Tallinn|Europe/Tallinn|EE|
Moscou|Moscow|Europe/Moscow|RU|moskva
Saint-Pétersbourg|Saint Petersburg|Europe/Moscow|RU|saint-petersbourg,st petersburg,st. petersburg
Istanbul|Istanbul|Europe/Istanbul|TR|
Ankara|Ankara|Europe/Istanbul|TR|
Nicosie|Nicosia|Asia/Nicosia|CY|
La Valette|Valletta|Europe/Malta|MT|
Monaco|Monaco|Europe/Monaco|MC|
Andorre-la-Vieille|Andorra la Vella|Europe/Andorra|AD|
Dubaï|Dubai|Asia/Dubai|AE|dubai
Abou Dabi|Abu Dhabi|Asia/Dubai|AE|abu dhabi,abou dhabi
Doha|Doha|Asia/Qatar|QA|
Riyad|Riyadh|Asia/Riyadh|SA|riyadh
Djeddah|Jeddah|Asia/Riyadh|SA|jeddah
Koweït|Kuwait City|Asia/Kuwait|KW|koweit,kuwait
Manama|Manama|Asia/Bahrain|BH|
Mascate|Muscat|Asia/Muscat|OM|muscat
Téhéran|Tehran|Asia/Tehran|IR|teheran
Bagdad|Baghdad|Asia/Baghdad|IQ|baghdad
Amman|Amman|Asia/Amman|JO|
Beyrouth|Beirut|Asia/Beirut|LB|beirut
Damas|Damascus|Asia/Damascus|SY|damascus
Jérusalem|Jerusalem|Asia/Jerusalem|IL|jerusalem
Tel Aviv|Tel Aviv|Asia/Jerusalem|IL|tel-aviv
Le Caire|Cairo|Africa/Cairo|EG|caire,cairo
Rabat|Rabat|Africa/Casablanca|MA|
Casablanca|Casablanca|Africa/Casablanca|MA|
Marrakech|Marrakesh|Africa/Casablanca|MA|marrakesh
Alger|Algiers|Africa/Algiers|DZ|algiers
Tunis|Tunis|Africa/Tunis|TN|
Dakar|Dakar|Africa/Dakar|SN|
Abidjan|Abidjan|Africa/Abidjan|CI|
Bamako|Bamako|Africa/Bamako|ML|
Ouagadougou|Ouagadougou|Africa/Ouagadougou|BF|
Niamey|Niamey|Africa/Niamey|NE|
Conakry|Conakry|Africa/Conakry|GN|
Lomé|Lome|Africa/Lome|TG|lome
Cotonou|Cotonou|Africa/Porto-Novo|BJ|porto-novo
Accra|Accra|Africa/Accra|GH|
Lagos|Lagos|Africa/Lagos|NG|
Abuja|Abuja|Africa/Lagos|NG|
Yaoundé|Yaounde|Africa/Douala|CM|yaounde
Douala|Douala|Africa/Douala|CM|
Libreville|Libreville|Africa/Libreville|GA|
Brazzaville|Brazzaville|Africa/Brazzaville|CG|
Kinshasa|Kinshasa|Africa/Kinshasa|CD|
Luanda|Luanda|Africa/Luanda|AO|
Nairobi|Nairobi|Africa/Nairobi|KE|
Addis-Abeba|Addis Ababa|Africa/Addis_Ababa|ET|addis ababa,addis abeba
Kampala|Kampala|Africa/Kampala|UG|
Kigali|Kigali|Africa/Kigali|RW|
Dar es Salaam|Dar es Salaam|Africa/Dar_es_Salaam|TZ|
Khartoum|Khartoum|Africa/Khartoum|SD|
Djibouti|Djibouti|Africa/Djibouti|DJ|
Johannesburg|Johannesburg|Africa/Johannesburg|ZA|
Le Cap|Cape Town|Africa/Johannesburg|ZA|cape town
Pretoria|Pretoria|Africa/Johannesburg|ZA|
Antananarivo|Antananarivo|Indian/Antananarivo|MG|tananarive
Port-Louis|Port Louis|Indian/Mauritius|MU|port louis
Tokyo|Tokyo|Asia/Tokyo|JP|tokio
Osaka|Osaka|Asia/Tokyo|JP|
Kyoto|Kyoto|Asia/Tokyo|JP|
Séoul|Seoul|Asia/Seoul|KR|seoul
Pékin|Beijing|Asia/Shanghai|CN|pekin,beijing
Shanghai|Shanghai|Asia/Shanghai|CN|shanghaï
Shenzhen|Shenzhen|Asia/Shanghai|CN|
Canton|Guangzhou|Asia/Shanghai|CN|guangzhou
Hong Kong|Hong Kong|Asia/Hong_Kong|HK|hongkong,hong-kong
Macao|Macau|Asia/Macau|MO|macau
Taipei|Taipei|Asia/Taipei|TW|taipei
Singapour|Singapore|Asia/Singapore|SG|singapore
Kuala Lumpur|Kuala Lumpur|Asia/Kuala_Lumpur|MY|
Bangkok|Bangkok|Asia/Bangkok|TH|
Hanoï|Hanoi|Asia/Ho_Chi_Minh|VN|hanoi
Hô Chi Minh-Ville|Ho Chi Minh City|Asia/Ho_Chi_Minh|VN|ho chi minh,saigon,hô-chi-minh-ville,ho chi minh ville
Phnom Penh|Phnom Penh|Asia/Phnom_Penh|KH|
Vientiane|Vientiane|Asia/Vientiane|LA|
Rangoun|Yangon|Asia/Yangon|MM|yangon,rangoon
Jakarta|Jakarta|Asia/Jakarta|ID|djakarta
Manille|Manila|Asia/Manila|PH|manila
New Delhi|New Delhi|Asia/Kolkata|IN|delhi,new-delhi
Bombay|Mumbai|Asia/Kolkata|IN|mumbai
Bangalore|Bengaluru|Asia/Kolkata|IN|bengaluru
Calcutta|Kolkata|Asia/Kolkata|IN|kolkata
Chennai|Chennai|Asia/Kolkata|IN|madras
Islamabad|Islamabad|Asia/Karachi|PK|
Karachi|Karachi|Asia/Karachi|PK|
Lahore|Lahore|Asia/Karachi|PK|
Dacca|Dhaka|Asia/Dhaka|BD|dhaka
Katmandou|Kathmandu|Asia/Kathmandu|NP|kathmandu
Colombo|Colombo|Asia/Colombo|LK|
Kaboul|Kabul|Asia/Kabul|AF|kabul
Tachkent|Tashkent|Asia/Tashkent|UZ|tashkent
Almaty|Almaty|Asia/Almaty|KZ|
Astana|Astana|Asia/Almaty|KZ|
Bakou|Baku|Asia/Baku|AZ|baku
Tbilissi|Tbilisi|Asia/Tbilisi|GE|tbilisi
Erevan|Yerevan|Asia/Yerevan|AM|yerevan
Oulan-Bator|Ulaanbaatar|Asia/Ulaanbaatar|MN|ulaanbaatar,oulan bator
Sydney|Sydney|Australia/Sydney|AU|
Canberra|Canberra|Australia/Sydney|AU|
Melbourne|Melbourne|Australia/Melbourne|AU|
Brisbane|Brisbane|Australia/Brisbane|AU|
Perth|Perth|Australia/Perth|AU|
Adélaïde|Adelaide|Australia/Adelaide|AU|adelaide
Auckland|Auckland|Pacific/Auckland|NZ|
Wellington|Wellington|Pacific/Auckland|NZ|
Nouméa|Noumea|Pacific/Noumea|NC|noumea
Papeete|Papeete|Pacific/Tahiti|PF|tahiti
Honolulu|Honolulu|Pacific/Honolulu|US|hawaii,hawaï
New York|New York|America/New_York|US|new-york,nyc,manhattan
Washington|Washington, D.C.|America/New_York|US|washington dc,washington d.c.
Boston|Boston|America/New_York|US|
Philadelphie|Philadelphia|America/New_York|US|philadelphia
Miami|Miami|America/New_York|US|
Atlanta|Atlanta|America/New_York|US|
Chicago|Chicago|America/Chicago|US|
Houston|Houston|America/Chicago|US|
Dallas|Dallas|America/Chicago|US|
La Nouvelle-Orléans|New Orleans|America/Chicago|US|nouvelle-orleans,new orleans
Denver|Denver|America/Denver|US|
Phoenix|Phoenix|America/Phoenix|US|
Los Angeles|Los Angeles|America/Los_Angeles|US|los-angeles
San Francisco|San Francisco|America/Los_Angeles|US|
Seattle|Seattle|America/Los_Angeles|US|
Las Vegas|Las Vegas|America/Los_Angeles|US|
Anchorage|Anchorage|America/Anchorage|US|
Ottawa|Ottawa|America/Toronto|CA|
Montréal|Montreal|America/Toronto|CA|montreal
Toronto|Toronto|America/Toronto|CA|
Québec|Quebec City|America/Toronto|CA|quebec,ville de québec
Vancouver|Vancouver|America/Vancouver|CA|
Calgary|Calgary|America/Edmonton|CA|
Halifax|Halifax|America/Halifax|CA|
Saint-Jean de Terre-Neuve|St. John's|America/St_Johns|CA|st john's,terre-neuve,newfoundland
Mexico|Mexico City|America/Mexico_City|MX|mexico city,ciudad de mexico
Cancún|Cancun|America/Cancun|MX|cancun
La Havane|Havana|America/Havana|CU|havana,la habana
Saint-Domingue|Santo Domingo|America/Santo_Domingo|DO|santo domingo
Port-au-Prince|Port-au-Prince|America/Port-au-Prince|HT|
Pointe-à-Pitre|Pointe-à-Pitre|America/Guadeloupe|GP|guadeloupe,pointe a pitre
Fort-de-France|Fort-de-France|America/Martinique|MQ|martinique
Cayenne|Cayenne|America/Cayenne|GF|guyane
Panama|Panama City|America/Panama|PA|panama city
San José (Costa Rica)|San José (Costa Rica)|America/Costa_Rica|CR|costa rica
Bogota|Bogotá|America/Bogota|CO|bogotá
Caracas|Caracas|America/Caracas|VE|
Quito|Quito|America/Guayaquil|EC|
Lima|Lima|America/Lima|PE|
La Paz|La Paz|America/La_Paz|BO|
Santiago du Chili|Santiago|America/Santiago|CL|santiago,santiago de chile
Buenos Aires|Buenos Aires|America/Argentina/Buenos_Aires|AR|
Montevideo|Montevideo|America/Montevideo|UY|
Asuncion|Asunción|America/Asuncion|PY|asunción
Brasilia|Brasília|America/Sao_Paulo|BR|brasília
São Paulo|São Paulo|America/Sao_Paulo|BR|sao paulo,sao-paulo
Rio de Janeiro|Rio de Janeiro|America/Sao_Paulo|BR|rio
Saint-Denis (La Réunion)|Saint-Denis (Réunion)|Indian/Reunion|RE|réunion island
Mayotte|Mayotte|Indian/Mayotte|YT|mamoudzou
"""

# country names FR/EN -> the table's city that answers for it (its capital, or its largest business city)
_COUNTRIES = """
France,la France=Paris
Royaume-Uni,Angleterre,Grande-Bretagne,UK,United Kingdom,England,Britain=Londres
Irlande,Ireland=Dublin
Belgique,Belgium=Bruxelles
Pays-Bas,Hollande,Netherlands,Holland=Amsterdam
Suisse,Switzerland=Berne
Allemagne,Germany=Berlin
Autriche,Austria=Vienne (Autriche)
Espagne,Spain=Madrid
Portugal=Lisbonne
Italie,Italy=Rome
Grèce,Greece=Athènes
Danemark,Denmark=Copenhague
Suède,Sweden=Stockholm
Norvège,Norway=Oslo
Finlande,Finland=Helsinki
Islande,Iceland=Reykjavik
Pologne,Poland=Varsovie
Tchéquie,République tchèque,Czechia,Czech Republic=Prague
Hongrie,Hungary=Budapest
Roumanie,Romania=Bucarest
Bulgarie,Bulgaria=Sofia
Croatie,Croatia=Zagreb
Serbie,Serbia=Belgrade
Ukraine=Kyiv
Russie,Russia=Moscou
Turquie,Turkey,Türkiye=Istanbul
Émirats arabes unis,Emirats,UAE,United Arab Emirates=Dubaï
Arabie saoudite,Saudi Arabia=Riyad
Qatar=Doha
Israël,Israel=Jérusalem
Liban,Lebanon=Beyrouth
Iran=Téhéran
Égypte,Egypt=Le Caire
Maroc,Morocco=Rabat
Algérie,Algeria=Alger
Tunisie,Tunisia=Tunis
Sénégal,Senegal=Dakar
Côte d'Ivoire,Ivory Coast=Abidjan
Mali=Bamako
Burkina Faso=Ouagadougou
Cameroun,Cameroon=Yaoundé
Gabon=Libreville
Nigeria=Abuja
Ghana=Accra
Kenya=Nairobi
Éthiopie,Ethiopia=Addis-Abeba
Afrique du Sud,South Africa=Johannesburg
Madagascar=Antananarivo
Maurice,île Maurice,Mauritius=Port-Louis
Japon,Japan=Tokyo
Corée du Sud,Corée,South Korea,Korea=Séoul
Chine,China=Pékin
Taïwan,Taiwan=Taipei
Singapour,Singapore=Singapour
Malaisie,Malaysia=Kuala Lumpur
Thaïlande,Thailand=Bangkok
Vietnam,Viêt Nam=Hanoï
Indonésie,Indonesia=Jakarta
Philippines=Manille
Inde,India=New Delhi
Pakistan=Islamabad
Bangladesh=Dacca
Népal,Nepal=Katmandou
Sri Lanka=Colombo
Australie,Australia=Sydney
Nouvelle-Zélande,New Zealand=Auckland
Nouvelle-Calédonie,New Caledonia=Nouméa
Polynésie française,French Polynesia=Papeete
États-Unis,Etats-Unis,USA,US,United States,Amérique=Washington
Canada=Ottawa
Mexique,Mexico=Mexico
Cuba=La Havane
Colombie,Colombia=Bogota
Pérou,Peru=Lima
Chili,Chile=Santiago du Chili
Argentine,Argentina=Buenos Aires
Brésil,Brazil=Brasilia
"""
# a country spread over several zones answers with its capital, and the card says so
MULTI_ZONE = {"US", "CA", "RU", "BR", "AU", "MX", "ID", "KZ", "CL", "PT", "ES", "EC", "FR"}


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").replace("’", "'").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w']+", " ", t).split())


class City(dict):
    """{'fr', 'en', 'zone', 'cc', 'country'?: True when it stands for a whole country}"""

    def name(self, lang: str) -> str:
        return self["en"] if lang == "en" else self["fr"]


CITIES: list[City] = []
_ALIAS: dict[str, City] = {}
for _line in _TABLE.strip().splitlines():
    _fr, _en, _zone, _cc, _more = _line.split("|")
    _c = City(fr=_fr, en=_en, zone=_zone, cc=_cc)
    CITIES.append(_c)
    for _a in [_fr, _en, re.sub(r"\s*\(.*\)$", "", _fr), *[x for x in _more.split(",") if x]]:
        _ALIAS.setdefault(fold(_a), _c)
_BY_FR = {c["fr"]: c for c in CITIES}
COUNTRIES: dict[str, City] = {}
for _line in _COUNTRIES.strip().splitlines():
    _names, _city = _line.split("=")
    _cap = _BY_FR[_city]
    for _n in _names.split(","):
        COUNTRIES.setdefault(fold(_n), City(_cap, country=_names.split(",")[0], country_en=_names.split(",")[-1]))
_CC_ZONE = {}
for _c in CITIES:
    _CC_ZONE.setdefault(_c["cc"], set()).add(_c["zone"])


def zone_for_country(cc: str) -> str:
    """The zone of a single-zone country (ISO code), from this table; '' for an unknown or multi-zone one."""
    cc = (cc or "").upper()
    zones = _CC_ZONE.get(cc, set())
    return next(iter(zones)) if len(zones) == 1 and cc not in MULTI_ZONE else ""


_FR_OVERSEAS = re.compile(
    r"guadeloupe|martinique|guyane|r[ée]union|mayotte|cal[ée]donie|polyn[ée]sie|saint-pierre|wallis|barth[ée]lemy|"
    r"saint-martin|terres australes|clipperton",
    re.I,
)


def country_zone(cc: str, region: str = "", country: str = "") -> str:
    """Zone of a geocoded town from its COUNTRY (never its coordinates): a single-zone country of the table, or
    metropolitan France (France spans 12 zones: a town is metropolitan when its region is not an overseas one)."""
    cc = (cc or "").upper()
    if cc == "FR":
        return "" if _FR_OVERSEAS.search(f"{region} {country}") else "Europe/Paris"
    return zone_for_country(cc)


def lookup(name: str, ctx, lang: str = "fr") -> City | None:
    """A town missing from the table, by geocoding its name (the user's own words) to learn its country."""
    from birds.harness import geo

    hits = sorted(geo.Geocoder(ctx).search(name, limit=3, lang=lang), key=lambda h: -(h.importance or 0.0))
    if not hits:
        return None
    p = hits[0]
    zone = country_zone(p.country_code, p.region, p.country)
    if not zone:
        return None
    return City(fr=p.name, en=p.name, zone=zone, cc=p.country_code)


def valid_zone(name: str | None) -> str:
    """The browser's zone when it is a real IANA name, else Europe/Paris."""
    if name and len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_+\-/]+", name):
        try:
            ZoneInfo(name)
            return name
        except (ValueError, KeyError, OSError):
            pass
    return DEFAULT_TZ


def city_of_zone(zone: str) -> City | None:
    """The first table city of a zone (the user's own zone, e.g. Europe/Paris -> Paris)."""
    return next((c for c in CITIES if c["zone"] == zone), None)


# ---------------------------------------------------------------- detection

_TIME_ASK = re.compile(
    r"(?<!\ba )(?<!\bà )\b(?:quelle heure (?:est[ -]il|il est|est il|fait[ -]il)|il est quelle heure|"
    r"l'heure (?:qu'il est |locale |actuelle )?(?:a|à|au|aux|en|de|du|d')|heures? locales?|"
    r"what time is it|what's the time|what is the time|(?:current|local) time|time (?:is it )?(?:now )?in)\b",
    re.I,
)
_OFFSET_ASK = re.compile(
    r"\b(?:d[ée]calages? horaires?|d[ée]calage (?:avec|entre)|diff[ée]rences? (?:d'heures?|horaires?)|"
    r"fuseaux? horaires?|heures? de d[ée]calage|time differences?|time zones?|timezones?|jet ?lag|"
    r"hours? (?:ahead|behind))\b",
    re.I,
)
_SLOT_ASK = re.compile(
    r"\b(?:cr[ée]neaux?(?: horaires?)?(?: communs?)?|plages? horaires?|horaires? communs?|heures? communes?|"
    r"moment commun|quand (?:appeler|joindre|organiser|planifier|caler)|à quelle heure (?:appeler|organiser|caler)|"
    r"(?:common|shared|overlapping|best) (?:time ?slots?|slots?|hours|times?|meeting times?)|meeting times?|"
    r"time ?slots?|when (?:to|can we|should we|could we) (?:call|meet|schedule))\b",
    re.I,
)
# no lone « point » (« fais le point », « un point avec Nice entre 10h et 11h ») and no « call » alone in French prose
_MEETING = re.compile(r"\b(?:r[ée]union|visio|appel|meeting|rendez-vous|rdv|r[ée]unir|meet|call)\b", re.I)
# « entre Londres et Singapour » / « between London and New York », never « entre 10h et 11h »
_BETWEEN = re.compile(
    r"\b(?:entre|between)\s+(?!\d)(?P<a>[^,;?!.]+?)\s+(?:et|and|&)\s+(?!\d)(?P<b>[^,;?!.]+?)(?=$|[,;?!.]|\s+(?:pour|for|"
    r"sur|on|le|la|ce|cette|demain|lundi|mardi|mercredi|jeudi|vendredi|this|next)\b)",
    re.I,
)


def _meeting_between(raw: str) -> bool:
    """A meeting « entre X et Y » where X and Y each name a city or country of the table."""
    if not _MEETING.search(raw):
        return False
    for m in _BETWEEN.finditer(raw):
        if _names_in(m.group("a")) and _names_in(m.group("b")):
            return True
    return False
_NOT_CLOCK = re.compile(
    r"\b(?:heures? (?:de pointe|sup\w*|suppl[ée]mentaires?|creuses?|pleines?)|rush hour|overtime|"
    r"heures? de vol|flight time|heures? de (?:travail|trajet)|travel time)\b",
    re.I,
)
_UNKNOWN_AFTER = re.compile(
    r"\b(?:quelle heure (?:est[ -]il|il est|est il)|il est quelle heure|what time is it|time (?:is it )?(?:now )?in)"
    r"\s+(?:à|a|au|en|in|at)\s+(?P<name>[A-ZÀ-Ý][\w'À-ÿ-]+(?:[ -][A-ZÀ-Ý][\w'À-ÿ-]+){0,3})",
)


# « la réunion » is a meeting: the island only as « île de la Réunion », « à la Réunion », « La Réunion »
# (capital L and R, so not « pour la Réunion budget ») or « Réunion island »
_REUNION = re.compile(r"\b(?:[îiÎI]le\s+de\s+la|(?:à|a|À)\s+la|(?<![\w'])La)\s+R[ée]union\b(?!\s+[Ii]sland)")
# « Saint-Denis » alone is the town of Seine-Saint-Denis (Paris time); the Réunion's capital only when the island
# is said: « Saint-Denis de la Réunion », « Saint-Denis (La Réunion) », « Saint-Denis, Réunion »
_SAINT_DENIS_RE = re.compile(
    r"\bS(?:ain)?t[- ]Denis\s*(?:\(\s*|,\s*|-\s*)?(?:(?:de|à|a|sur\s+l'[îi]le\s+de)\s+)?(?:la\s+|l'[îi]le\s+de\s+la\s+)?"
    r"R[ée]union\b\)?",
    re.I,
)


def _names_in(text: str) -> list[City]:
    """Table cities and countries named in ``text``, in the order written (longest name first at a spot)."""
    f = f" {fold(_REUNION.sub(' Réunion island ', _SAINT_DENIS_RE.sub(' Réunion island ', text)))} "
    hits: list[tuple[int, int, City]] = []
    for table in (_ALIAS, COUNTRIES):
        for alias, city in table.items():
            if len(alias) < 3 and alias not in ("us", "uk"):
                continue
            for m in re.finditer(rf"(?<=\s){re.escape(alias)}(?=\s)", f):
                hits.append((m.start(), -len(alias), city))
    hits.sort(key=lambda x: (x[0], x[1]))
    out, taken = [], -1
    for start, neg, city in hits:
        if start <= taken:
            continue
        taken = start - neg
        if city.get("country") and fold(city["country"]) in ("us",) and not re.search(r"\bUS\b|\bUSA\b", text):
            continue  # « us » in English prose is a pronoun: only the capitals US / USA name the country
        if not any(c["fr"] == city["fr"] and bool(c.get("country")) == bool(city.get("country")) for c in out):
            out.append(city)
    return out


def detect(text: str) -> dict | None:
    """{'mode': 'time'|'offset'|'slot', 'cities': [City], 'unknown': str} or None. The user's own words only."""
    raw = " ".join((text or "").replace("’", "'").split())
    if not raw or _NOT_CLOCK.search(raw):
        return None
    if _TIME_ASK.search(raw):
        mode = "time"
    elif _OFFSET_ASK.search(raw):
        mode = "offset"
    elif _SLOT_ASK.search(raw) or _meeting_between(raw):
        mode = "slot"
    else:
        return None
    cities = _names_in(raw)[:MAX_CITIES]
    unknown = ""
    if not cities and mode == "time":
        m = _UNKNOWN_AFTER.search(raw)
        unknown = m.group("name") if m else ""
    if not cities and not unknown:
        return None
    if mode == "slot" and len(cities) < 2 and not _OFFSET_ASK.search(raw):
        # « trouve un créneau avec Lyon » alone: one city is a calendar question unless its zone differs (card())
        if not cities:
            return None
    return {"mode": mode, "cities": cities, "unknown": unknown}


# ---------------------------------------------------------------- time maths


def offset_minutes(zone: str, at: datetime) -> int:
    return int(at.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() // 60)


def offset_label(minutes: int, ascii_minus: bool = False) -> str:
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else ("-" if ascii_minus else "−")
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def _office(zone: ZoneInfo, at: datetime, span: tuple[int, int]) -> bool:
    loc = at.astimezone(zone)
    mins = loc.hour * 60 + loc.minute
    return loc.weekday() < 5 and span[0] <= mins and mins + STEP <= span[1]


def work_day(now_local: datetime, day: date | None = None) -> date:
    """The day of the timeline: the one asked, else today, else (weekend) next Monday."""
    d = day or now_local.date()
    while d.weekday() >= 5 and day is None:
        d += timedelta(days=1)
    return d


def day_columns(user_zone: str, day: date) -> list[datetime]:
    """24 hourly instants from the user's local midnight (a DST day still gets 24 real hours, labelled as they are)."""
    z = ZoneInfo(user_zone)
    start = datetime(day.year, day.month, day.day, tzinfo=z).astimezone(UTC)
    return [start + timedelta(hours=i) for i in range(24)]


def _ranges(flags: list[bool], start: datetime) -> list[tuple[datetime, datetime]]:
    out, run = [], None
    for i, ok in enumerate(flags + [False]):
        t = start + timedelta(minutes=STEP * i)
        if ok and run is None:
            run = t
        elif not ok and run is not None:
            out.append((run, t))
            run = None
    return out


def common_slots(zones: list[str], user_zone: str, day: date, span: tuple[int, int] = OFFICE):
    """Instants of ``day`` (user's zone) when every zone is within ``span`` local, Monday-Friday: [(start, end)]."""
    zs = [ZoneInfo(z) for z in zones]
    start = day_columns(user_zone, day)[0]
    n = 24 * 60 // STEP
    flags = [all(_office(z, start + timedelta(minutes=STEP * i), span) for z in zs) for i in range(n)]
    return _ranges(flags, start)


def card(
    found: dict, now: datetime, lang: str = "fr", user_zone: str = DEFAULT_TZ, day: date | None = None
) -> dict | None:
    """The clock widget: each city's local time; for 2-4 distinct zones, the office-hours day and common slot(s)."""
    lang = "en" if lang == "en" else "fr"
    try:
        uz = ZoneInfo(user_zone)
    except (ValueError, KeyError, OSError):
        user_zone, uz = DEFAULT_TZ, ZoneInfo(DEFAULT_TZ)
    now = now.astimezone(uz)
    cities = list(found.get("cities") or [])
    if not cities:
        return None
    rows = []
    for c in cities:
        rows.append({"name": c.name(lang), "zone": c["zone"], "cc": c["cc"], "user": False,
                     "country": (c.get("country_en") if lang == "en" else c.get("country")) or "",
                     "multi": bool(c.get("country")) and c["cc"] in MULTI_ZONE})  # fmt: skip
    zones = list(dict.fromkeys(r["zone"] for r in rows))
    if user_zone not in zones or (found.get("mode") != "slot" and len(rows) == 1 and zones == [user_zone]):
        if user_zone not in zones:
            me = city_of_zone(user_zone)
            label = me.name(lang) if me else user_zone.rsplit("/", 1)[-1].replace("_", " ")
            rows.insert(0, {"name": label, "zone": user_zone, "cc": me["cc"] if me else "", "user": True,
                            "country": "", "multi": False})  # fmt: skip
            zones.insert(0, user_zone)
    for r in rows:
        r["user"] = r["user"] or (r["zone"] == user_zone and not any(x["user"] for x in rows))
    if found.get("mode") in ("slot", "offset") and len(zones) < 2:
        return None  # every city in the user's zone: a calendar question, not a clock one
    my_off = offset_minutes(user_zone, now)
    for r in rows:
        loc = now.astimezone(ZoneInfo(r["zone"]))
        r["offset_min"] = offset_minutes(r["zone"], now)
        r["offset"] = offset_label(r["offset_min"])
        r["diff_min"] = r["offset_min"] - my_off
        r["local"] = loc.strftime("%Y-%m-%dT%H:%M")
        r["day_shift"] = (loc.date() - now.date()).days
    widget = {
        "type": "clock",
        "v": 1,
        "mode": found.get("mode", "time"),
        "now": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user_tz": user_zone,
        "cities": rows,
        "office": [OFFICE[0] // 60, OFFICE[1] // 60],
    }
    if 2 <= len(zones) <= MAX_CITIES:
        d = work_day(now, day)
        cols = day_columns(user_zone, d)
        tl = []
        for r in rows:
            z = ZoneInfo(r["zone"])
            hours, office = [], []
            for t in cols:
                loc = t.astimezone(z)
                hours.append(loc.hour + (loc.minute / 60 if loc.minute else 0))
                office.append(sum(_office(z, t + timedelta(minutes=STEP * q), OFFICE) for q in range(60 // STEP)))
            tl.append({"hours": hours, "office": office})  # office: quarters of that hour within office hours
        common = common_slots(zones, user_zone, d, OFFICE)
        wide = [] if common else common_slots(zones, user_zone, d, WIDE)
        widget["timeline"] = {
            "date": d.isoformat(),
            "start": cols[0].strftime("%Y-%m-%dT%H:%MZ"),  # the user's local midnight, as an instant
            "user_hours": [t.astimezone(uz).hour for t in cols],
            "rows": tl,
        }
        widget["common"] = [_slot(a, b, rows) for a, b in common]
        widget["wide"] = [_slot(a, b, rows) for a, b in wide]
    return widget


def _slot(a: datetime, b: datetime, rows: list[dict]) -> dict:
    return {
        "start": a.strftime("%Y-%m-%dT%H:%MZ"),
        "end": b.strftime("%Y-%m-%dT%H:%MZ"),
        "local": [
            [a.astimezone(ZoneInfo(r["zone"])).strftime("%H:%M"), b.astimezone(ZoneInfo(r["zone"])).strftime("%H:%M")]
            for r in rows
        ],  # fmt: skip
    }


_DAYS = {"fr": "lundi mardi mercredi jeudi vendredi samedi dimanche".split(),
         "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()}  # fmt: skip
_MONTHS = {"fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
           "en": "January February March April May June July August September October November December".split()}  # fmt: skip


def day_label(d: date, lang: str) -> str:
    return f"{_DAYS[lang][d.weekday()]} {d.day} {_MONTHS[lang][d.month - 1]}"


def _diff(minutes: int, lang: str) -> str:
    if minutes == 0:
        return "même heure" if lang == "fr" else "same time"
    h, m = divmod(abs(minutes), 60)
    span = f"{h} h {m:02d}" if m else f"{h} h"
    if lang == "en":
        span = f"{h}h{m:02d}" if m else f"{h}h"
        return f"{span} {'ahead' if minutes > 0 else 'behind'}"
    return f"{span} de {'plus' if minutes > 0 else 'moins'}"


def _minutes(s: dict) -> float:
    a = datetime.strptime(s["start"], "%Y-%m-%dT%H:%MZ")
    b = datetime.strptime(s["end"], "%Y-%m-%dT%H:%MZ")
    return (b - a).total_seconds() / 60


def summary(w: dict, lang: str = "fr") -> str:
    """The facts for the model, computed here: it only has to put them in one sentence."""
    lang = "en" if lang == "en" else "fr"
    rows = w["cities"]
    me = next((r for r in rows if r["user"]), rows[0])
    parts = []
    for r in rows:
        hm = r["local"][11:]
        shift = ""
        if r["day_shift"]:
            d = date.fromisoformat(r["local"][:10])
            shift = f", {day_label(d, lang)}"
        rel = "" if r is me else f", {_diff(r['diff_min'], lang)}"
        tag = (" (vous)" if lang == "fr" else " (you)") if r is me else ""
        multi = (" — capitale ; le pays a plusieurs fuseaux" if lang == "fr" else
                 " — capital; the country has several zones") if r.get("multi") else ""  # fmt: skip
        parts.append(f"{r['name']}{tag} {hm} ({offset_label(r['offset_min'], True)}{rel}{shift}){multi}")
    head = "Heures locales calculées par Bird" if lang == "fr" else "Local times computed by Bird"
    out = f"{head} : " + " ; ".join(parts) + "."
    if "timeline" in w and w.get("mode") in ("slot", "offset"):  # a plain « quelle heure » gets the times only
        d = date.fromisoformat(w["timeline"]["date"])
        i_me = rows.index(me)
        dl = day_label(d, lang)
        if w["common"]:
            slots = ", ".join(f"{s['local'][i_me][0]}–{s['local'][i_me][1]}" for s in w["common"])
            others = "; ".join(
                f"{r['name']} " + ", ".join(f"{s['local'][i][0]}–{s['local'][i][1]}" for s in w["common"])
                for i, r in enumerate(rows)
                if r is not me
            )
            out += (
                f" Créneau commun aux heures de bureau (9 h–18 h, lundi-vendredi), {dl} : {slots} heure de "
                f"{me['name']} (soit {others})."
                if lang == "fr"
                else f" Common office-hours slot (9am-6pm, Monday-Friday), {dl}: {slots} {me['name']} time "
                f"(i.e. {others})."
            )
        elif w["wide"]:
            s = max(w["wide"], key=_minutes)
            others = "; ".join(f"{r['name']} {s['local'][i][0]}–{s['local'][i][1]}" for i, r in enumerate(rows)
                               if r is not me)  # fmt: skip
            out += (
                f" Aucun créneau commun aux heures de bureau (9 h–18 h) le {dl}. Compromis en horaires élargis "
                f"(7 h–21 h) : {s['local'][i_me][0]}–{s['local'][i_me][1]} heure de {me['name']} (soit {others}), "
                "tôt ou tard pour certains."
                if lang == "fr"
                else f" No common office-hours slot (9am-6pm) on {dl}. Compromise within extended hours (7am-9pm): "
                f"{s['local'][i_me][0]}–{s['local'][i_me][1]} {me['name']} time (i.e. {others}), early or late "
                "for some."
            )
        else:
            out += (
                f" Aucun créneau commun, même en horaires élargis (7 h–21 h), le {dl}."
                if lang == "fr"
                else f" No common slot on {dl}, even within extended hours (7am-9pm)."
            )
    return out
