"""Deterministic reading of the user's OWN words: does this request ask for places, a company or a conversion?

Bird S 4B was never trained on find_places / find_company / convert_currency. So the harness does the work: when
a parser below is confident it returns the tool call itself (``Intent.args``), which the agent runs before the
first generation ("prefill", tagged "automatic" in the UI); when it only sees a hint it returns ``args=None`` and
the tool is merely offered. Pure functions, no I/O: see tests/test_intents.py.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Intent:
    tool: str  # "find_places" | "find_company" | "convert_currency"
    args: dict | None  # None: offer the tool, do not call it
    keep_web: bool = True  # False: web_search / read_page withdrawn for this turn
    mode: str = ""  # places: near | route | where | list | address


# ---------------------------------------------------------------- normalisation

_POLITE = re.compile(r"\b(?:s'il te pla[iî]t|s'il vous pla[iî]t|stp|svp|please|merci)\b", re.I)
_LEAD = re.compile(
    r"^(?:(?:bonjour|bonsoir|salut|hello|hi)\b[\s,!]*|"
    # « pourriez-vous m'indiquer où… », « est-ce que tu peux me dire où… », « dis-moi où… », « je voudrais l'adresse… »
    r"(?:est-ce que |pourrais-tu |peux-tu |pouvez-vous |pourriez-vous |tu peux |tu sais |sais-tu |savez-vous |"
    r"can you |could you )?(?:tu peux |pourrais-tu |peux-tu |pourriez-vous )?(?:me dire |m'indiquer |me donner )|"
    r"dis-moi |je voudrais (?:savoir |conna[iî]tre )?|j'aimerais (?:savoir |conna[iî]tre )?|"
    r"(?:est-ce que |pourrais-tu |peux-tu |pouvez-vous |tu peux |can you |could you )?"
    r"(?:montre(?:-moi)?|affiche(?:-moi)?|donne(?:-moi)?|trouve(?:-moi)?|cherche(?:-moi)?|indique(?:-moi)?|"
    r"liste(?:-moi)?|propose(?:-moi)?|conseille(?:-moi)?|recommande(?:-moi)?|je cherche|"
    r"show(?: me)?|find(?: me)?|give me|tell me|list|recommend|suggest)\b[\s,:]*)",
    re.I,
)


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").replace("’", "'")
    t = _POLITE.sub(" ", t)
    t = " ".join(t.split()).strip(" ?!.,;:")
    for _ in range(2):
        t = _LEAD.sub("", t).strip(" ?!.,;:")
    return t


# ---------------------------------------------------------------- places

# surface form (regex) -> Nominatim keyword
KINDS: list[tuple[str, str]] = [
    (r"restaurants?|restos?", "restaurant"),
    (r"caf[ée]s?|coffee shops?", "cafe"),
    (r"bars?|pubs?", "bar"),
    (r"h[ôo]tels?", "hotel"),
    (r"pharmacies?|pharmacy", "pharmacy"),
    (r"parkings?|car parks?", "parking"),
    (r"banques?|banks?", "bank"),
    (r"distributeurs?(?: de billets)?|dab|atms?|cash machines?", "atm"),
    (r"supermarch[ée]s?|supermarkets?", "supermarket"),
    (r"stations?[- ]service|gas stations?|petrol stations?", "fuel"),
    (r"garages?(?: auto(?:mobiles?)?)?|m[ée]caniciens?|car repairs?|garagistes?", "car_repair"),
    (r"boulangeries?|bakery|bakeries", "bakery"),
    (r"bornes? de recharge|charging stations?", "charging station"),
    (r"coworkings?|espaces? de coworking", "coworking"),
    (r"salles? de r[ée]union|meeting rooms?", "conference centre"),
    (r"bureaux? de poste|postes?|post offices?", "post office"),
    (r"gares?|train stations?", "train station"),
    (r"stations? de m[ée]tro|m[ée]tros?|subway stations?", "subway station"),
    (r"h[ôo]pitaux|h[ôo]pital|hospitals?", "hospital"),
    (r"m[ée]decins?|doctors?", "doctors"),
    (r"imprimeries?|copy ?shops?|print shops?", "copyshop"),
    (r"librairies?|bookshops?|bookstores?", "bookshop"),
    (r"mus[ée]es?|museums?", "museum"),
    (r"cin[ée]mas?|cinemas?", "cinema"),
    (r"salles? de sport|gyms?", "fitness centre"),
    (r"cr[èe]ches?|nurseries", "kindergarten"),
    (r"[ée]coles?|schools?", "school"),
    (r"brasseries?", "restaurant"),
    (r"pizzerias?", "pizza"),
    (r"fleuristes?|florists?", "florist"),
    (r"laveries?|laundrettes?", "laundry"),
]
_KIND = "(?P<kind>" + "|".join(f"(?:{k})" for k, _ in KINDS) + ")"
_NAME = r"(?P<{}>[^?!\n]{{2,80}})"

_NEAR_WORDS = (
    r"(?:près\s+d(?:e\s+|u\s+|es\s+|')|pres\s+d(?:e\s+|u\s+|es\s+|')|à\s+côté\s+d(?:e\s+|u\s+|es\s+|')|"
    r"a\s+cote\s+d(?:e\s+|u\s+|')|autour\s+d(?:e\s+|u\s+|es\s+|')|proches?\s+d(?:e\s+|u\s+|es\s+|')|"
    r"aux\s+alentours\s+d(?:e\s+|u\s+|es\s+|')|dans\s+le\s+quartier\s+d(?:e\s+|u\s+|es\s+|')|vers\s+|"
    r"near\s+|around\s+|close\s+to\s+|next\s+to\s+|by\s+|"
    r"[àa]\s+proximit[ée]\s+d(?:e\s+|u\s+|es\s+|')|"
    # « une pharmacie à Nantes », « un garage dans Versailles »: a kind in a town (letters after it, never « à 100 € »)
    r"(?:à|a|dans|sur|in)\s+(?=[^\W\d_]))"
)
_ART = r"(?:la\s+|le\s+|l'|les\s+|the\s+)?"
_RX_NEAR = re.compile(
    r"(?:^|\b)(?:des\s+|les\s+|un\s+|une\s+|quelques\s+|bons?\s+|meilleurs?\s+|good\s+|some\s+|a\s+|the\s+)?"
    + _KIND
    + r"(?:\s+[\w-]+){0,4}?\s+"  # « hôtels y a-t-il autour de… »
    + _NEAR_WORDS
    + _ART
    + _NAME.format("near"),
    re.I,
)
_RX_ROUTE = re.compile(
    r"(?:itin[ée]raire|trajet|comment\s+(?:aller|se\s+rendre)|directions?|route|how\s+(?:do\s+i\s+|to\s+)?get)"
    r"\s+(?:de\s+|du\s+|depuis\s+|from\s+)" + _ART + r"(?P<a>[^?!\n]{2,80}?)\s+(?:à\s+|a\s+|au\s+|jusqu'à\s+|"
    r"jusqu'au\s+|vers\s+|to\s+)" + _ART + _NAME.format("b"),
    re.I,
)
_RX_ROUTE1 = re.compile(
    r"(?:itin[ée]raire|trajet|comment\s+(?:aller|se\s+rendre)|directions?|how\s+(?:do\s+i\s+|to\s+)?get)"
    r"\s+(?:à\s+|au\s+|aux\s+|vers\s+|jusqu'à\s+|jusqu'au\s+|pour\s+(?:aller\s+(?:à\s+|au\s+))?|to\s+)"
    + _ART
    + _NAME.format("b"),
    re.I,
)
_RX_WHERE = re.compile(
    # typed fast on a phone: « ou es la boutique… », « c est ou le siège… » (never « où en est le projet »)
    r"^(?:o[uù]\s+(?:se\s+trouve(?:nt)?|se\s+situe(?:nt)?|est|es|ets|sont|son)(?:\s+situ[ée]e?s?)?(?:\s+exactement)?|"
    r"c'?\s?est\s+o[uù](?:\s+(?:exactement|donc|d[ée]j[àa]))?|(?:what'?s|what\s+is)\s+the\s+address\s+of|"
    r"(?:quelle\s+est\s+)?l?'?adresse\s+(?:de\s+|du\s+|des\s+|d')|localise(?:-moi)?|"
    r"(?:une\s+)?carte\s+(?:de\s+|du\s+|des\s+|d')|(?:un\s+)?plan\s+(?:d'accès|de\s+situation)\s+(?:de\s+|du\s+|d'|des\s+)?|"
    r"where(?:\s+is|'s|\s+are)|(?:the\s+)?address\s+of|(?:a\s+)?map\s+of|locate)(?:\s+|(?<=[\s']))"
    + _ART
    + r"(?:(?:ville|city)\s+(?:de\s+|d'|of\s+))?"
    + _NAME.format("q"),
    re.I,
)
_RX_SITUE_MAP = re.compile(  # « situe Nantes sur une carte », « (montre-moi) Lyon sur une carte »
    r"^(?:situe(?:-moi)?\s+" + _ART + r"(?P<q>[^?!\n]{2,80}?)|(?P<q2>[^\W\d_][\w'-]+(?:\s+[^\W\d_][\w'-]+)?))"
    r"\s+sur\s+(?:une|la)\s+carte\b",
    re.I,
)
# an explicit map ask: any target is a place (« carte de la bretagne »)
_MAP_ASK = re.compile(r"^(?:(?:une\s+)?carte\b|(?:a\s+)?map\b|localise|locate|situe)|\bsur\s+(?:une|la)\s+carte\b", re.I)
# « les parkings de aix »: a plural kind of place in a town, said bare
_RX_KIND_OF = re.compile(r"^(?:les\s+|des\s+)?" + _KIND + r"\s+(?:de\s+|du\s+|d')(?P<near>[^\W\d_][\w' -]{1,40})$", re.I)
_NOT_TOWN = re.compile(  # « les écoles de commerce », « les pharmacies de garde »: a complement, not a town
    r"^(?:garde|commerce|nuit|jour|luxe|sport|langues?|musique|danse|conduite|cuisine|ing[ée]nieurs?|management|"
    r"art|design|formation|quartier|proximit[ée]|ville|campagne|montagne|mer|charme|r[ée]f[ée]rence|qualit[ée]|"
    r"l'entreprise|entreprise|soir|week-end)\b",
    re.I,
)
# « itinéraire Lyon Grenoble », « trajet paris marseille »
_RX_ROUTE_BARE = re.compile(r"^(?:itin[ée]raire|trajet)\s+(?P<a>[^\W\d_][\w'-]+)\s+(?:(?:->|[-–>→])\s*)?(?P<b>[^\W\d_][\w'-]+)$", re.I)
_NOT_STOP = re.compile(
    r"^(?:domicile|travail|boulot|maison|retour|aller|quotidien|formation|professionnel|carri[èe]re|"
    r"le|la|les|de|du|des|pour|en|vers|optimal|rapide|direct|habituel)$",
    re.I,
)
_ARTICLE_BEFORE = re.compile(r"(?:\b(?:la|le|les|the|un|une|des)\s+|l')$", re.I)
_TOWNISH = re.compile(r"[^\W\d_][\w'-]+(?:\s+(?:en|sur)\s+[^\W\d_][\w'-]+|\s+[^\W\d_][\w'-]+)?")
_APPS = re.compile(  # office software and tools: « où est Teams ? » asks for a menu, not a map
    r"(?i:excel|word|outlook|teams|powerpoint|power point|sharepoint|onedrive|one drive|drive|google drive|slack|"
    r"intranet|extranet|notion|jira|confluence|zoom|gmail|sap|salesforce|trello|asana|dropbox|onenote|"
    r"windows|chrome|firefox|safari|edge|acrobat|photoshop|canva|figma|github|gitlab)"
)
_NOT_TARGET = re.compile(  # « c'est où que je change… », « où est passée ma commande », « c'est où demain ? »
    r"^(?:qu|pass[ée]e?s?\b|demain\b|aujourd'hui\b|hier\b|maintenant\b|ce soir\b|tomorrow\b|today\b|now\b|"
    r"ensuite\b|apr[èe]s\b|maman\b|papa\b|mamie\b|papi\b|papy\b|mom\b|mum\b|dad\b)",
    re.I,
)
_POSSESSIVE = re.compile(r"^(?:mon|ma|mes|ton|ta|tes|son|sa|ses|notre|nos|votre|vos|leurs?|my|your|our|his|her|their)\b", re.I)
_LIST_NOUNS = (
    r"(?:sites|adresses|lieux|agences|bureaux|magasins|boutiques|villes|implantations|entrepôts|entrepots|"
    r"locations|offices|stores|places|cities|sites)"
)
_RX_LIST = re.compile(
    r"(?:compare|situe|place|localise|carte|map|mets\s+sur\s+(?:une|la)\s+carte|show\s+on\s+a\s+map)\s+"
    r"(?:ces\s+|les\s+|nos\s+|these\s+|our\s+)?(?:\d+\s+|deux\s+|trois\s+|quatre\s+|cinq\s+|two\s+|three\s+|"
    r"four\s+|five\s+)?" + _LIST_NOUNS + r"(?:\s+[^:\n]{0,60})?\s*:\s*(?P<list>.+)",
    re.I,
)
_PLACE_WORD = re.compile(
    r"\b(?:adresse|carte|plan|map|où|ou se|itin[ée]raire|trajet|localise|situe|aller|venir|accès|acces|address|"
    r"where|directions?)\b",
    re.I,
)
_HINT = re.compile(  # never the bare word "plan": "fais-moi un plan pour la présentation" is an outline
    r"\b(?:carte|plan d'accès|plan de situation|map|itin[ée]raire|adresse|lieux?|o[uù] (?:se trouve|est)|près d|"
    r"à côté d|near|nearby|where)\b",
    re.I,
)
_NEVER = re.compile(
    r"\b(?:fichiers?|dossiers?|documents?|boutons?|menus?|onglets?|r[ée]glages?|param[èe]tres?|options?|projets?|tickets?|bugs?|"
    r"erreurs?|code|fonction|variable|cellule|colonne|e-?mails?|mail|courriel|adresse (?:ip|mac|e-?mail|mail|url|web)|"
    r"urls?|liens?|site web|website|pages?|slides?|diapos?|en est|on en est|files?|folders?|buttons?|settings?|projects?|"
    r"spreadsheet|ip address|email address|"
    r"carte (?:graphique|de visite|bancaire|bleue|cadeau|son|m[èe]re|sim|vitale|grise|de fidélité|mentale|heuristique)|"
    r"mind ?map|"
    r"plan (?:d'action|de formation|de charge|comptable|marketing|projet|de financement|social|de table|"
    r"de travail|de communication|de continuit[ée])|business plan|action plan|graphics card|credit card)\b",
    re.I,
)
# the OBJECT of "où est / adresse de / where is" is a document, a meeting or an office notion: never a place ask
_DOC_TARGET = re.compile(
    r"\b(?:contrats?|rapports?|reports?|dossiers?|fichiers?|files?|documents?|docs?|mails?|e-?mails?|courriels?|"
    r"r[ée]unions?|meetings?|factur\w*|invoices?|billing|devis|notes?|comptes?[- ]rendus?|cr|compta\w*|"
    r"pr[ée]sentations?|slides?|diapos?|tableurs?|budgets?|pi[èe]ces? jointes?|attachments?|pdf|contexte|essentiel|"
    r"points?|ordres? du jour|agenda|planning|proc[ée]dures?|process|mentionn\w*|ce contrat|ce document|summary|"
    r"synth[èe]se|minutes|deck|draft|brouillon|q[1-4]|diff[ée]rences?|int[ée]r[êe]ts?|probl[èe]mes?|soucis?|"
    r"avantages?|inconv[ée]nients?|logique|valeur|value|deal|catch|difference|problem|issue|point mort|solutions?)\b",
    re.I,
)
# a person: civility, colleague, a home, or a common first name followed by a surname (never geocoded)
_PERSON_WORDS = re.compile(
    r"(?:\b(?:Mme|Mlle|Monsieur|Madame|Mademoiselle|Mrs|Ms|Mr|Dr)\b\.?|\bM\.\s|"
    r"\b(?:mon|ma|mes|notre|nos|my|our)\s+(?:coll[èe]gues?|colleagues?|coworkers?|manager|cheff?e?|boss|"
    r"stagiaires?|employ[ée]e?s?|salari[ée]e?s?|assistante?)\b|\b(?:habite\w*|domicile|vit|vivent|lives?|living|"
    r"home address|adresse (?:perso\w*|priv[ée]e|du domicile))\b)",
    re.I,
)
FIRST_NAMES = frozenset(
    """jean pierre paul jacques michel philippe alain nicolas thomas julien antoine louis lucas hugo léo leo arthur
    gabriel raphaël raphael jules adam nathan théo theo maxime alexandre olivier christophe laurent stéphane stephane
    sébastien sebastien vincent françois francois patrick david eric éric frédéric frederic marc bruno didier
    guillaume romain mathieu matthieu benoît benoit damien pascal thierry yves henri marie anne sophie julie camille
    claire isabelle nathalie sandrine céline celine catherine christine sylvie valérie valerie laura léa lea emma
    chloé chloe manon sarah inès ines alice louise jade lina zoé zoe juliette pauline caroline aurélie aurelie émilie
    emilie hélène helene charlotte mathilde lucie agnès agnes martine françoise francoise monique nicole brigitte
    john james robert michael william richard joseph charles mary patricia jennifer linda elizabeth susan jessica
    karen emily anna peter mark steven kevin brian george edward daniel matthew andrew joshua chris tom tim mike
    """.split()
)
_LANDMARK = re.compile(
    r"\b(?:tour|gare|mairie|h[ôo]tel de ville|pr[ée]fecture|place|rue|avenue|av|boulevard|bd|quai|pont|parc|jardin|"
    r"square|mus[ée]e|ch[âa]teau|cath[ée]drale|basilique|[ée]glise|abbaye|palais|op[ée]ra|th[ée][âa]tre|stade|"
    r"a[ée]roport|port|plage|lac|mont|col|for[êe]t|universit[ée]|campus|lyc[ée]e|coll[èe]ge|h[ôo]pital|clinique|"
    r"si[èe]ge|zone|quartier|centre|ville|village|r[ée]gion|d[ée]partement|arc|cit[ée]|march[ée]|halles?|"
    r"tower|station|airport|museum|park|bridge|street|road|cathedral|castle|palace|city|town|beach|lake|"
    r"mountain|island|[îi]le|monument|memorial|stadium|university|headquarters|hq|campus)\b",
    re.I,
)


# Towns, regions and countries a user may type in lowercase (« ou est nantes », « trajet paris marseille ») or that
# name a place, not a company or a team (« combien de salariés à Paris »). Accents and case are ignored.
KNOWN_PLACES = frozenset(
    """paris marseille lyon toulouse nice nantes montpellier strasbourg bordeaux lille rennes reims toulon
    saint-etienne le-havre grenoble dijon angers nimes villeurbanne clermont-ferrand le-mans aix aix-en-provence brest
    tours amiens limoges annecy perpignan boulogne-billancourt metz besancon orleans rouen mulhouse caen nancy
    argenteuil montreuil saint-denis roubaix tourcoing avignon poitiers versailles nanterre creteil pau la-rochelle
    calais cannes antibes colmar bourges vierzon chartres lens arras dunkerque valence ajaccio bastia bayonne biarritz
    lorient vannes quimper saint-malo cherbourg niort angouleme troyes chambery blois laval beauvais evry cergy massy
    orly roissy toussus-le-noble saclay vincennes neuilly levallois issy courbevoie puteaux saint-cloud meudon rueil
    vichy valenciennes douai cholet saint-nazaire montauban albi rodez carcassonne beziers sete narbonne frejus hyeres
    gap auxerre nevers macon belfort epinal thionville charleville sedan compiegne soissons evreux lisieux alencon
    aurillac tarbes lourdes agen perigueux brive tulle gueret moulins chateauroux deauville honfleur chamonix lens
    bretagne normandie alsace lorraine provence corse bourgogne auvergne aquitaine occitanie champagne picardie savoie
    vendee ile-de-france idf paca hauts-de-france grand-est nouvelle-aquitaine pays-de-la-loire centre-val-de-loire
    auvergne-rhone-alpes bourgogne-franche-comte cote-d'azur landes dordogne gironde finistere morbihan jura vosges
    ardeche drome isere vaucluse herault haute-savoie
    france belgique suisse allemagne espagne italie portugal royaume-uni angleterre ecosse irlande pays-bas hollande
    luxembourg autriche pologne grece suede norvege danemark finlande maroc algerie tunisie senegal canada quebec usa
    etats-unis mexique bresil argentine chine japon inde australie russie turquie egypte europe afrique asie
    london londres new-york berlin madrid barcelone barcelona rome milan turin venise florence naples lisbonne lisbon
    porto bruxelles brussels anvers gand liege geneve geneva lausanne zurich berne bale amsterdam rotterdam la-haye
    munich francfort frankfurt hambourg cologne vienne prague varsovie budapest athenes dublin edimbourg manchester
    stockholm oslo copenhague helsinki montreal toronto vancouver tokyo pekin shanghai hong-kong singapour dubai
    casablanca rabat marrakech tunis alger dakar abidjan istanbul moscou los-angeles san-francisco chicago boston
    washington miami sydney melbourne monaco
    """.split()
)
_ARTICLE_LEAD = re.compile(r"^(?:la|le|les|l'|the)\s*", re.I)


def _fold(text: str) -> str:
    """'Île-de-France' -> 'ile-de-france', 'côte d'Azur' -> 'cote-d'azur': lowercase, no accents, hyphens for spaces."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().replace("’", "'")
    return re.sub(r"\s+", "-", _ARTICLE_LEAD.sub("", t.strip(" .,;:!?")))


def known_place(q: str) -> bool:
    """A town, region or country from KNOWN_PLACES, or a compound town name (« saint-cyr », « villers-sur-mer »)."""
    f = _fold(q)
    if f in KNOWN_PLACES:
        return True
    return bool(re.fullmatch(r"(?:saint|sainte|st|ste)-[a-z'-]+|[a-z']+-(?:sur|en|le|la|les|de|d'|lès|les|sous)-[a-z'-]+", f))


# « carte de vœux », « carte des vins », « carte de crédit »: a card or a list, never a map
_NOT_A_MAP_CARD = re.compile(
    r"\bcartes?\s+(?:de\s+|des\s+|d')?(?:v[œo]e?ux|vins?|cr[ée]dit|s[ée]jour|membres?|restaurant|menus?|desserts|"
    r"boissons|identit[ée]|transport|navigo|d[ée]bit|paiement|r[ée]seau|m[ée]moire|[ée]lecteur|professionnelle|"
    r"blanche|jeux?|t[ée]l[ée]phone|carburant|essence|embarquement|abonnement|fid[ée]lit[ée]|r[ée]duction|"
    r"anniversaire|remerciements?|condol[ée]ances|f[ée]licitations|no[ëe]l|invitation|achat|stationnement|"
    r"[ée]tudiante?|europ[ée]enne d'assurance|grise|vitale|bancaire|cadeau|visite|presse|famille|senior|jeune)\b",
    re.I,
)


def _person(q: str) -> bool:
    if _PERSON_WORDS.search(q):
        return True
    words = re.findall(r"[\wÀ-ÿ'-]+", q)
    for i, w in enumerate(words):  # "Paul", "Paul Martin", "contrat de Jean Dupont"
        if w.lower() in FIRST_NAMES and w[:1].isupper():
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if not nxt or nxt[:1].isupper():
                return True
    return False


def _not_a_place(q: str) -> bool:
    """The object names a document, a meeting, an office notion or a person: no place intent at all."""
    return bool(_DOC_TARGET.search(q) or (_person(q) and not _LANDMARK.search(q)))


def _placey(q: str) -> bool:
    """A place-like target worth an automatic call: a proper noun, a landmark noun, an address or a kind."""
    from birds.harness.geo import looks_like_address

    if looks_like_address(q) or _LANDMARK.search(q) or _kind_in(q):
        return True
    if any(w[:1].isupper() for w in re.findall(r"[\wÀ-ÿ'-]+", q)):
        return True
    # typed all lowercase on a phone: « boutique du pilote a toussus », « garage martin à saint-cyr »
    return bool(re.search(r"\s(?:à|a|au|aux|in|near|pr[eè]s\s+de)\s+[a-zà-ÿ][\wà-ÿ'-]{2,}(?:[\s-][\wà-ÿ'-]+){0,3}$", q))


def _kind_in(q: str) -> bool:
    return any(re.search(rf"\b(?:{rx})\b", q, re.I) for rx, _ in KINDS)


_HOWTO = re.compile(
    r"^\s*(?:comment (?:faire|ajouter|cr[ée]er|changer|modifier|ins[ée]rer)|how (?:do|can|to) "
    r"(?:i |you )?(?:add|create|change|insert|make))\b",
    re.I,
)


_DEICTIC = re.compile(
    r"(?:là|la|ici|là-bas|here|there|it|chez (?:lui|elle|eux|moi|nous)|cet endroit|ce lieu|cette adresse|"
    r"this place|that place)",
    re.I,
)


_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)
_PERSON_HOME = re.compile(
    r"\b(?:o[uù] (?:habite|vit|loge|demeure)\w*|where (?:does|do|did) .{1,60}? (?:live|stay)|"
    r"adresse (?:perso\w*|priv[ée]e|du domicile)|home address)\b",
    re.I,
)


def _plural(words: str) -> bool:
    """« pharmacies », « hôtels », « bureaux »: the first word is plural. « la gare de Lyon » names one place."""
    first = (words or "").split()[0] if (words or "").split() else ""
    return first.lower().endswith(("s", "x"))


def _kind_of(word: str) -> str:
    for rx, key in KINDS:
        if re.fullmatch(rx, word.strip(), re.I):
            return key
    return ""


def _clean_name(text: str) -> str:
    t = re.split(
        r"\s+(?:et|and|puis|then|pour|for|avec|with)\s+(?:me\s+|moi\s+)?(?:fais|fait|donne|dis|"
        r"pr[ée]pare|écris|ecris|envoie|make|give|tell|write|send)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    t = re.split(r"[?!.;\n]|\s+[-–—]\s+|,\s+(?:et|and|fais|donne|make|give)\b", t, maxsplit=1)[0]
    return " ".join(t.split()).strip(" ,:'\"")


def _ok(name: str) -> bool:
    return 2 <= len(name) <= 80 and not _NEVER.search(name)


def places(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join(_URL.sub(" ", text or "").split())
    if not raw or _NEVER.search(raw) or _NOT_A_MAP_CARD.search(raw) or _HOWTO.search(raw) or _PERSON_HOME.search(raw):
        return None
    t = normalise(raw)
    m = _RX_LIST.search(t)
    if m:
        items = [
            i.strip(" .") for i in re.split(r"[,;\n]|\s+et\s+|\s+and\s+|\s+-\s+", m.group("list")) if i.strip(" .")
        ]
        items = [_clean_name(i) for i in items]
        items = [i for i in items if _ok(i) and not _not_a_place(i)]
        if 2 <= len(items) <= 5:
            return Intent("find_places", {"query": " ; ".join(items)}, keep_web=True, mode="list")
    m = _RX_NEAR.search(t)
    if m and not _plural(m.group("kind")) and re.match(
        r"\s+(?:de\s+la\s+|de\s+l'|de\s+|du\s+|des\s+|d')(?:[A-ZÀ-Ý]|ville\b)", t[m.end("kind"):]
    ):
        m = None  # « l'hôtel de la Paix à Genève »: one named place, looked up whole below
    if m and re.search(r"itin[ée]raire|trajet|comment (?:aller|se rendre)|directions?|how (?:do i |to )?get", t, re.I) \
            and not re.search(r"pr[eè]s d|autour d|[àa] c[ôo]t[ée] d|proches? d|alentours|near|around|close to", t, re.I):
        m = None  # « itinéraire de la gare de Lyon à la tour Eiffel »: a route, the « à » is its destination
    if m:
        near = _clean_name(m.group("near"))
        kind = _kind_of(m.group("kind"))
        if kind and _DEICTIC.fullmatch(near):  # "près de là": the place is in the conversation, not in these words
            return Intent("find_places", None, keep_web=False)
        if kind and _ok(near):
            if _not_a_place(near) or re.match(r"chez\b", near, re.I):  # "près de chez Paul": a private home
                return None
            return Intent("find_places", {"query": kind, "near": near}, keep_web=False, mode="near")
    m = _RX_ROUTE.search(t)
    if m:
        a, b = _clean_name(m.group("a")), _clean_name(m.group("b"))
        if _ok(a) and _ok(b):
            if _not_a_place(a) or _not_a_place(b):
                return None
            if _placey(a) and _placey(b):
                return Intent("find_places", {"query": b, "near": a}, keep_web=False, mode="route")
            return Intent("find_places", None, keep_web=True)
    m = _RX_ROUTE1.search(t)
    if m:
        b = _clean_name(m.group("b"))
        parts = re.split(r"\s+(?:depuis|en partant d(?:e|u|es)|from)\s+" + _ART, b, maxsplit=1, flags=re.I)
        if len(parts) == 2:  # « comment aller à la tour Eiffel depuis la gare de Lyon »: destination, then start
            dest, origin = _clean_name(parts[0]), _clean_name(parts[1])
            if _ok(dest) and _ok(origin) and not _not_a_place(dest) and not _not_a_place(origin):
                return Intent("find_places", {"query": dest, "near": origin}, keep_web=False, mode="route")
        if _ok(b):
            if _not_a_place(b):
                return None  # "comment aller à l'essentiel dans une présentation"
            if _placey(b):
                return Intent("find_places", {"query": b}, keep_web=False, mode="route")
            return Intent("find_places", None, keep_web=True)
    from birds.harness.geo import find_address

    addr = find_address(raw)  # a typed postal address wins over "où est ..." (BAN geocodes it exactly)
    if addr and _PLACE_WORD.search(raw):
        addr = re.sub(r"\s+(?:à|a|in)\s+(?=[A-ZÀ-Ý])", " ", addr)
        return Intent("find_places", {"query": addr}, keep_web=False, mode="address")
    m = _RX_KIND_OF.match(t)
    if m and _plural(m.group("kind")) and not _NOT_TOWN.match(m.group("near")) and _ok(m.group("near")):
        near = _clean_name(m.group("near"))
        if not (near[:1].isupper() or known_place(near)):  # « les restaurants du coin »: where is not said
            return Intent("find_places", None, keep_web=True)
        return Intent(
            "find_places", {"query": _kind_of(m.group("kind")), "near": _clean_name(m.group("near"))},
            keep_web=False, mode="near",
        )
    m = _RX_ROUTE_BARE.match(t)
    # « trajet client fournisseur », « itinéraire marketing digital »: two words are a route only when both are
    # towns (known, or capitalised) or joined by an arrow or a dash
    stops = m and (re.search(r"[-–>→]\s*\S+$", t[m.end("a"):]) or all(
        known_place(m.group(k)) or m.group(k)[:1].isupper() for k in ("a", "b")))  # fmt: skip
    if m and stops and not _NOT_STOP.match(m.group("a")) and not _NOT_STOP.match(m.group("b")):
        if not _not_a_place(m.group("a")) and not _not_a_place(m.group("b")):
            return Intent("find_places", {"query": m.group("b"), "near": m.group("a")}, keep_web=False, mode="route")
    m = _RX_WHERE.search(t) or _RX_SITUE_MAP.search(t)
    if m:
        g = "q" if m.groupdict().get("q") else "q2"
        q = _clean_name(m.group(g))
        if re.fullmatch(r"(?:il|elle|ça|ca|it|they|là|la)", q, re.I):
            return Intent("find_places", None, keep_web=True)
        if not _ok(q) or _not_a_place(q) or _NOT_TARGET.match(q):
            return None  # "où est le contrat de Paul Martin", "where is the Q3 report": not a place at all
        landmark = bool(_LANDMARK.search(q) or _kind_in(q))
        words = re.findall(r"[\wÀ-ÿ'-]+", q)
        if _POSSESSIVE.match(q):  # « où est ma commande », « où est mon hôtel »: never geocoded as written
            return Intent("find_places", None, keep_web=True) if landmark else None
        if not landmark and all(w.lower() in FIRST_NAMES for w in words):
            return None  # « ou est sophie »: a person
        # « les parkings de aix », « pharmacies à Lyon »: a plural kind of place in a town is a "near" search;
        # a singular one names a place (« la gare de Lyon », « le musée d'Orsay »), looked up whole
        kn = re.match(r"(?P<kind>.+?)\s+(?:de|du|d'|à|a|au|aux|in|of)\s*(?P<near>[^\s].*)$", q, re.I)
        if kn and _kind_of(kn.group("kind")) and _plural(kn.group("kind")) and len(kn.group("near")) >= 3:
            return Intent(
                "find_places", {"query": _kind_of(kn.group("kind")), "near": _clean_name(kn.group("near"))},
                keep_web=False, mode="near",
            )
        if _APPS.fullmatch(q):
            return None  # « où est Excel ? », « ou est outlook »: software, never a place
        # a bare town typed in lowercase (« ou est nantes », « where is lyon »): no article and a known town
        before = t[: m.start(g)]
        bare = not _ARTICLE_BEFORE.search(before)
        town = bare and bool(_TOWNISH.fullmatch(q)) and known_place(q)
        # « où est Dupont ? », « où est Martin ? »: one capitalised word that is no known town may be a surname
        lone = bare and len(words) == 1 and "-" not in q and not landmark and not known_place(q) and not re.search(
            r"(?:ville|city|town|commune)\s+(?:de\s+|d'|of\s+)$", before, re.I
        )
        if lone and not _MAP_ASK.search(t):
            return Intent("find_places", None, keep_web=True)
        # an explicit map ask (« carte de la bretagne ») still needs a place-like target: never « carte de X pour … »
        explicit = _MAP_ASK.search(t) and (_placey(q) or known_place(q))
        if _placey(q) or town or explicit:
            return Intent("find_places", {"query": q}, keep_web=False, mode="where")
        return Intent("find_places", None, keep_web=True)
    if _HINT.search(raw):
        if _DOC_TARGET.search(raw) and not re.search(r"\b(?:carte|map|itin[ée]raire|plan d'accès)\b", raw, re.I):
            return None
        return Intent("find_places", None, keep_web=True)
    return None


def split_near(query: str) -> tuple[str, str] | None:
    """'restaurants près de la gare de Lyon' -> ('restaurant', 'gare de Lyon'), for a model's call without near."""
    m = _RX_NEAR.search(normalise(query))
    if not m:
        return None
    kind, near = _kind_of(m.group("kind")), _clean_name(m.group("near"))
    return (kind, near) if kind and near else None


# ---------------------------------------------------------------- company


def luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


_SIRET = re.compile(r"(?<!\d)(\d{3}[  ]?\d{3}[  ]?\d{3}[  ]?\d{5})(?!\d)")
_SIREN = re.compile(r"(?<!\d)(\d{3}[  ]?\d{3}[  ]?\d{3})(?![\d])")
_SIREN_WORD = re.compile(r"\b(?:siren|siret|n° d'entreprise|num[ée]ro d'entreprise|registre|rcs)\b", re.I)
_COMPANY_ASK = re.compile(
    r"(?i:fiche|infos?|informations|renseignements|siren|siret|kbis|coordonn[ée]es|adresse|si[èe]ge|qui est|"
    r"c'est quoi|what is|about|tout sur|details? (?:on|of)|record|profile|look up|lookup)\s+(?:de\s+|sur\s+|du\s+|de la\s+|de l'|of\s+|on\s+)?"
    r"(?:la soci[ée]t[ée]|l'entreprise|la bo[iî]te|notre client|notre fournisseur|le client|le fournisseur|"
    r"the company|our client|our supplier|the supplier|the client)\s+"
    r"(?P<name>[A-Z0-9À-Ý][\w&'.\- ]{1,60})"
)
_COMPANY_HINT = re.compile(  # register cues only: "un fournisseur", "le restaurant d'entreprise" are ordinary words
    r"\b(?:siren|siret|kbis|raison sociale|company register|registre du commerce|rcs|n° tva|num[ée]ro de tva|"
    r"fiche (?:de la |d'une )?(?:soci[ée]t[ée]|entreprise)|infos? sur (?:la soci[ée]t[ée]|l'entreprise)|"
    r"(?:dirigeants?|chiffre d'affaires|effectifs?) de (?:la soci[ée]t[ée]|l'entreprise))\b",
    re.I,
)


# « qui dirige Michelin ? », « chiffre d'affaires de Leroy Merlin », « combien de salariés chez Doctolib »: a register
# question about a named company (capitalised, never a month, a quarter or a company form), or after a company noun
_COMPANY_ASK2 = re.compile(
    r"(?i:qui dirige|dirigeants?\s+(?:de|d'|du|chez)|chiffres? d'affaires\s+(?:de|d'|du)|\bCA\s+(?:de|d'|du)|"
    r"effectifs?\s+(?:de|d'|du|chez)|combien de salari[ée]s\s+(?:chez|[àa]|dans)|"
    r"(?:siren|siret|kbis|n° tva|num[ée]ro de tva)\s+(?:de|d'|du|chez)|who runs|who owns|revenue of)\s*"
    r"(?:(?i:la soci[ée]t[ée]|l'entreprise|la bo[iî]te|le groupe|the company)\s+(?P<lname>[\w&'.\- ]{2,60})|"
    r"(?!(?i:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
    r"january|february|march|april|june|july|august|september|october|november|december|Q[1-4]|T[1-4])\b)"
    r"(?!(?:PME|TPE|ETI|SARL|SAS|SA|SCI|SASU|EURL)\b)(?P<name>[A-ZÀ-Ý][\w&'.\- ]{1,60}))"
)
# « fiche entreprise doctolib »: a lowercase name only after an explicit company noun
_COMPANY_ASK_LOW = re.compile(
    r"(?i:\b(?:fiche|infos?|informations|renseignements)\s+(?:de\s+|sur\s+|du\s+)?"
    r"(?:la soci[ée]t[ée]|l'entreprise|entreprise|soci[ée]t[ée])\s+(?P<lname>[a-z0-9à-ÿ][\w&'.\- ]{1,60}))"
)
# « explique ce qu'est un numéro SIREN », « comment trouver le siret d'une entreprise ? »: about the register
_DEFINE = re.compile(
    r"\b(?:explique\w*|qu'est-ce qu|c'est quoi une?|comment (?:trouver|obtenir|lire|v[ée]rifier)|what is an?|"
    r"how (?:do i |to )?(?:find|get))\b",
    re.I,
)


def _company_name(name: str) -> str:
    return re.split(
        r"[?!.,;:]|\s+(?:et|and|pour|for|à|a|en|in|stp|svp|depuis|since|chez|sur|on|ce|cette|cet|ces|this|last|"
        r"l'an|l'ann[ée]e|le mois|la semaine|aujourd'hui|today|hier|demain|janvier|f[ée]vrier|mars|avril|mai|juin|"
        r"juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|(?:19|20)\d\d)\b",
        name,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" '")


# « effectifs de Lyon », « CA du Nord », « CA de Marc », « qui dirige Marketing / Projet Atlas »: a place, a person,
# a team or a project is an internal question, never a register lookup
_NOT_A_COMPANY = re.compile(
    r"^(?:nord|sud|est|ouest|north|south|east|west|centre|r[ée]gion|zone|secteur|marketing|rh|hr|ventes?|sales|"
    r"finances?|it|dsi|daf|informatique|direction|juridique|legal|compta\w*|achats?|communication|commercial|support|"
    r"logistique|production|qualit[ée]|sav|r&d|ressources humaines|engineering|produit|product|ops|op[ée]rations|"
    r"(?:projet|project|[ée]quipe|team|service|d[ée]partement|department|p[ôo]le|agence|site|magasin|boutique)\b.*)$",
    re.I,
)


def _internal_name(name: str) -> bool:
    return bool(_NOT_A_COMPANY.match(name) or known_place(name) or name.lower() in FIRST_NAMES)


def company_id(text: str) -> str:
    """A Luhn-valid SIRET (14 digits) or SIREN (9 digits) written in ``text``, digits only, or ''."""
    for rx in (_SIRET, _SIREN):
        for m in rx.finditer(text or ""):
            d = re.sub(r"\D", "", m.group(1))
            if luhn(d):
                return d
    return ""


def company(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join(_URL.sub(" ", (text or "").replace("’", "'")).split())
    if not raw or _HOWTO.search(raw):
        return None
    ident = company_id(raw)
    if ident and (_SIREN_WORD.search(raw) or _COMPANY_HINT.search(raw) or len(raw) < 40):
        return Intent("find_company", {"name": ident})
    m = _COMPANY_ASK.search(raw)
    if m:
        name = re.split(r"[?!.,;:]|\s+(?:et|and|pour|for|à|a|en|in)\s+", m.group("name"), maxsplit=1)[0].strip(" '")
        if 2 <= len(name) <= 60:
            return Intent("find_company", {"name": name})
    for rx in (_COMPANY_ASK2, _COMPANY_ASK_LOW):
        m = rx.search(raw)
        if m:
            name = _company_name(m.groupdict().get("name") or m.group("lname") or "")
            if m.groupdict().get("name") and _internal_name(name):
                break  # an internal KPI or org question: no register lookup
            if 2 <= len(name) <= 60:
                return Intent("find_company", {"name": name})
    if _COMPANY_HINT.search(raw) and not _DEFINE.search(raw):
        return Intent("find_company", None)
    return None


# ---------------------------------------------------------------- currencies

CURRENCIES = (
    "EUR USD JPY BGN CZK DKK GBP HUF PLN RON SEK CHF ISK NOK TRY AUD BRL CAD CNY HKD IDR ILS INR KRW MXN MYR NZD "
    "PHP SGD THB ZAR"
).split()
_CUR_WORDS: list[tuple[str, str]] = [
    (r"€|euros?|eur", "EUR"),
    (r"\$|us\$|dollars?\s+(?:am[ée]ricains?|us)|dollars? us|us dollars?|dollars?|usd", "USD"),
    (r"£|livres?\s+sterling|livres?|pounds?\s+sterling|pounds?|sterling|gbp", "GBP"),
    (r"¥|yens?|jpy", "JPY"),
    (r"francs?\s+suisses?|swiss\s+francs?|chf", "CHF"),
    (r"yuans?|renminbi|cny|rmb", "CNY"),
    (r"couronnes?\s+su[ée]doises?|swedish\s+kron(?:a|or)|sek", "SEK"),
    (r"couronnes?\s+danoises?|danish\s+kron(?:e|er)|dkk", "DKK"),
    (r"couronnes?\s+norv[ée]giennes?|norwegian\s+kron(?:e|er)|nok", "NOK"),
    (r"couronnes?\s+tch[èe]ques?|czech\s+korun(?:a|y)|czk", "CZK"),
    (r"zlotys?|pln", "PLN"),
    (r"dollars?\s+canadiens?|canadian\s+dollars?|cad", "CAD"),
    (r"dollars?\s+australiens?|australian\s+dollars?|aud", "AUD"),
    (r"roupies?|rupees?|inr", "INR"),
    (r"r[ée]als?\s+br[ée]siliens?|reais|brl", "BRL"),
    (r"forints?|huf", "HUF"),
    (r"livres?\s+turques?|turkish\s+liras?|lires?\s+turques?|try", "TRY"),
]
_GENERIC = ("USD", "GBP")  # « dollars », « livres »: tried after « dollars canadiens », « livres turques »
_CUR = (
    "(?:"
    + "|".join(w for w, c in _CUR_WORDS if c not in _GENERIC)
    + "|"
    + "|".join(w for w, c in _CUR_WORDS if c in _GENERIC)
    + "|"
    + "|".join(CURRENCIES)
    + ")"
)
_AMT = r"(?P<amt>\d[\d   .,]*(?:\s*(?:k|m|md|mds|million|millions|milliard|milliards|billion))?)"
_RX_FX = [
    re.compile(_AMT + r"\s*(?P<from>" + _CUR + r")\s+(?:en|in|to|into|vers|→|->)\s+(?P<to>" + _CUR + r")\b", re.I),
    re.compile(r"(?P<from>[€$£¥])\s*" + _AMT + r"\s+(?:en|in|to|into)\s+(?P<to>" + _CUR + r")\b", re.I),
    re.compile(
        r"(?:combien (?:vaut|valent|font|fait)|how much is|convertis(?:sez)?|convert)\s+"
        + _AMT
        + r"?\s*(?P<from>"
        + _CUR
        + r")\s+(?:en|in|to|into)\s+(?P<to>"
        + _CUR
        + r")\b",
        re.I,
    ),
    re.compile(
        r"(?:taux de change|cours|exchange rate)\s+(?:de l'|du |de |entre l'|entre le |entre |of |between |for )?"
        r"(?:the )?(?P<from>"
        + _CUR
        + r")\s*(?:et |en |contre |/|vs |and |to |against )?\s*(?:l'|le |la |the )?(?P<to>"
        + _CUR
        + r")\b",
        re.I,
    ),
    re.compile(r"\b(?P<from>[A-Z]{3})\s*/\s*(?P<to>[A-Z]{3})\b"),
    # « 500 yens ça fait combien en euros ? », « une facture de 3 400 USD, ça fait combien en euros ? »
    re.compile(
        _AMT + r"\s*(?P<from>" + _CUR + r")(?!\w)[^?!.]{0,40}?\bcombien\s+(?:en|in)\s+(?P<to>" + _CUR + r")\b", re.I
    ),
    # « le taux euro/livre »
    re.compile(
        r"\b(?:taux|cours|rate)\s+(?:de l'|du |de la |de |the )?(?P<from>" + _CUR + r")\s*/\s*(?P<to>" + _CUR + r")\b",
        re.I,
    ),
]
# only a source currency: the target is the euro (« combien vaut 1 000 CHF », « le cours du dollar aujourd'hui »);
# the end is anchored so « le cours du dollar depuis 2020 » (a trend) and « combien vaut 100 € en 2026 » stay out
_RX_FX_TO_EUR = [
    re.compile(
        r"(?:combien (?:vaut|valent|font|fait)|how much is|[çc]a fait combien)\s+" + _AMT + r"\s*(?P<from>" + _CUR
        + r")(?!\w)\s*(?:[?!.]|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:cours|taux)\s+(?:actuel\s+)?(?:du|de l'|de la)\s*(?P<from>" + _CUR
        + r")(?!\w)\s*(?:aujourd'hui|du jour|actuel)?\s*(?:[?!.]|$)",
        re.I,
    ),
]
# money in the words: an offer of convert_currency needs it (« convertis ce fichier en PDF » is not money). ISO codes
# are case-sensitive: the English word « try » is not TRY.
_CUR_ANY = re.compile(
    r"[€$£¥]|\b(?i:euros?|dollars?|livres? sterling|francs? suisses?|yens?|devises?|currenc(?:y|ies))\b|\b(?:"
    + "|".join(CURRENCIES)
    + r")\b"
)
_FX_HINT = re.compile(r"\b(?:taux de change|exchange rate|convertis|convert)\b", re.I)
_FX_KEEP_WEB = re.compile(
    r"\b(?:historique|[ée]volution|depuis|pr[ée]vision|forecast|history|trend|news|actualit)", re.I
)


def currency_code(word: str) -> str:
    w = " ".join((word or "").strip().lower().split())
    if w.upper() in CURRENCIES:
        return w.upper()
    for rx, code in _CUR_WORDS:
        if re.fullmatch(rx, w, re.I):
            return code
    return ""


def parse_amount(text: str) -> float | None:
    """'1 200' -> 1200, '1,5 M' -> 1500000, '12.50' -> 12.5, '1.200,50' -> 1200.5."""
    s = (text or "").strip().lower().replace(" ", " ").replace(" ", " ")
    mult = 1.0
    m = re.search(r"\s*(k|md|mds|milliards?|billion|m|millions?)$", s)
    if m:
        mult = {"k": 1e3, "m": 1e6, "million": 1e6, "millions": 1e6}.get(m.group(1), 1e9)
        s = s[: m.start()]
    s = s.replace(" ", "")
    if not s or not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head else s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3 and mult == 1.0):
        s = s.replace(".", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def fx(text: str, lang: str = "fr") -> Intent | None:
    raw = " ".join(_URL.sub(" ", (text or "").replace("’", "'")).split())
    if not raw:
        return None
    keep = bool(_FX_KEEP_WEB.search(raw))
    for rx in _RX_FX:
        m = rx.search(raw)
        if not m:
            continue
        a, b = currency_code(m.group("from")), currency_code(m.group("to"))
        if not a or not b or a == b:
            continue
        amt = parse_amount(m.groupdict().get("amt") or "") if m.groupdict().get("amt") else None
        args = {"from": a, "to": b}
        if amt is not None:
            args["amount"] = amt
        return Intent("convert_currency", args, keep_web=keep)
    for rx in _RX_FX_TO_EUR:
        m = rx.search(raw)
        if not m:
            continue
        a = currency_code(m.group("from"))
        if not a or a == "EUR":
            continue
        args = {"from": a, "to": "EUR"}
        amt = parse_amount(m.groupdict().get("amt") or "") if m.groupdict().get("amt") else None
        if amt is not None:
            args["amount"] = amt
        return Intent("convert_currency", args, keep_web=keep)
    if _FX_HINT.search(raw) and _CUR_ANY.search(raw):
        return Intent("convert_currency", None)
    return None


# ---------------------------------------------------------------- all together


def detect(text: str, attached: bool = False, lang: str = "fr") -> list[Intent]:
    """At most two intents, the prefilled one first. ``text`` = the user's own words (never attachment text)."""
    out: list[Intent] = []
    c = company(text, lang)
    p = places(text, lang)
    f = fx(text, lang)
    if attached and p:  # never an automatic lookup next to a document; find_places then only accepts the user's
        p = Intent("find_places", None)  # own words as query (tools/places.py), never an address read in the file
    if c and c.args:  # the register's address is authoritative: company wins the prefill, places is offered
        out.append(c)
        if p:
            out.append(Intent("find_places", None, keep_web=True))
    elif f and f.args:
        out.append(f)
    elif p and p.args:
        out.append(p)
        if c:
            out.append(c)
    else:
        out += [i for i in (p, c, f) if i]
    return out[:2]
