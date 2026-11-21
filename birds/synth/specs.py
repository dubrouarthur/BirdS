"""Deterministic, seeded scenario sampler for the teacher-generated data.

`sample(task, index, seed)` returns one scenario: a flat dict with the flags the converter and the
validator need (lang, thinking, system, register, kind...) and `brief`, the structured brief shown to
the teacher. Briefs are built combinatorially from the pools below; company, product and people
names are generated (fictional). Same (task, index, seed) => same scenario, on any machine.

Pool entries are `(french, english)` pairs. Nothing here is copied from the benchmark.
"""

from __future__ import annotations

import random

TARGETS = {
    "email_write": 12_000,
    "email_reply": 8_000,
    "email_rewrite": 4_000,
    "meeting_minutes": 8_000,
    "report_note": 6_000,
    "slides": 8_000,
    "web_research": 10_000,
    "tool_routing": 6_000,
    "sheet_formula": 4_000,
    "persona_chat": 4_000,
}
TASKS = list(TARGETS)
FR_SHARE = 0.65
# share of examples with reasoning; the weighted total is ~30 % of the 70 000 targets
THINKING = {
    "email_write": 0.05,
    "email_reply": 0.08,
    "email_rewrite": 0.05,
    "meeting_minutes": 0.15,
    "report_note": 0.70,
    "slides": 0.10,
    "web_research": 1.0,
    "tool_routing": 0.10,
    "sheet_formula": 0.70,
    "persona_chat": 0.05,
}
SYSTEM_MIX = (("default", 0.45), ("company", 0.25), ("none", 0.30))

# ---------------------------------------------------------------- names (all generated)
_S1 = [
    "Al",
    "Bré",
    "Cal",
    "Dor",
    "El",
    "Fen",
    "Gal",
    "Hel",
    "Is",
    "Jor",
    "Kal",
    "Lor",
    "Mar",
    "Nér",
    "Ol",
    "Per",
    "Quil",
    "Ros",
    "Sol",
    "Ter",
    "Ul",
    "Var",
    "Vel",
    "Zen",
    "Ar",
    "Bel",
    "Cor",
    "Dal",
    "Er",
    "Fal",
    "Gir",
    "Tal",
]
_S2 = [
    "vane",
    "miro",
    "dis",
    "tek",
    "via",
    "lune",
    "nor",
    "rine",
    "sys",
    "vea",
    "dane",
    "lis",
    "mond",
    "quet",
    "rac",
    "sane",
    "tal",
    "vox",
    "zia",
    "bert",
    "cade",
    "dor",
    "fine",
    "gane",
    "line",
    "mex",
    "pont",
    "rive",
    "sel",
    "tis",
]
# never produce a name that looks like a benchmark company or a well-known brand
_NAME_BLOCK = (
    "meridia",
    "lavigne",
    "kerbrat",
    "novalys",
    "vallon",
    "harlow",
    "northgate",
    "calder",
    "pinecrest",
    "lumen",
    "batipro",
    "arvor",
    "nordika",
    "logipro",
    "fleetwise",
    "delmas",
    "altis",
    "cortal",
    "solvea",
    "belmond",
    "calvia",
    "peltis",
    "altek",
    "orvane",
    "kerval",
    "vernet",
    "sorel",
    "nordis",
    "ardent",
    "hexa",
)
_FORMS = [
    ("{s}", "{s}"),
    ("Groupe {s}", "{s} Group"),
    ("{s} {tag}", "{s} {tag}"),
    ("{s} & Associés", "{s} & Partners"),
    ("Maison {s}", "{s} & Co"),
    ("{s} {tag}", "{s} {tag}"),
    ("Ateliers {s}", "{s} Works"),
    ("{s} {tag}", "{s} {tag}"),
]

FIRST_FR = [
    "Camille",
    "Léa",
    "Hugo",
    "Inès",
    "Julien",
    "Manon",
    "Thomas",
    "Sarah",
    "Antoine",
    "Chloé",
    "Mathieu",
    "Nadia",
    "Olivier",
    "Élodie",
    "Romain",
    "Aurélie",
    "Karim",
    "Pauline",
    "Florian",
    "Mélanie",
    "Bastien",
    "Solène",
    "Yanis",
    "Margaux",
    "Damien",
    "Laure",
    "Sébastien",
    "Amandine",
    "Quentin",
    "Fatima",
    "Guillaume",
    "Noémie",
    "Adrien",
    "Clémence",
    "Rémi",
    "Sophie",
    "Loïc",
    "Justine",
    "Cédric",
    "Anaïs",
    "Maxime",
    "Céline",
    "Arnaud",
    "Émilie",
    "Tristan",
    "Lucie",
    "Mehdi",
    "Charlotte",
    "Gaël",
    "Héloïse",
    "Benoît",
    "Marion",
    "Samuel",
    "Agathe",
]
LAST_FR = [
    "Morel",
    "Lefèvre",
    "Garnier",
    "Roussel",
    "Marchand",
    "Perrin",
    "Chevalier",
    "Boyer",
    "Renaud",
    "Aubert",
    "Lemoine",
    "Colin",
    "Brunet",
    "Vidal",
    "Caron",
    "Giraud",
    "Leclerc",
    "Barbier",
    "Guillot",
    "Poirier",
    "Charpentier",
    "Maillard",
    "Besson",
    "Tessier",
    "Hamon",
    "Jacquet",
    "Collet",
    "Bouvier",
    "Pichon",
    "Royer",
    "Lacroix",
    "Benali",
    "Carpentier",
    "Dupuis",
    "Meunier",
    "Fleury",
    "Klein",
    "Riviere",
    "Navarro",
    "Diallo",
    "Texier",
    "Le Gall",
    "Bertin",
    "Cordier",
    "Lebrun",
    "Hoarau",
    "Gauthier",
    "Marechal",
    "Prevost",
    "Sauvage",
]
FIRST_EN = [
    "Olivia",
    "Daniel",
    "Priya",
    "Marcus",
    "Hannah",
    "Owen",
    "Grace",
    "Liam",
    "Nadia",
    "Callum",
    "Sofia",
    "Ethan",
    "Megan",
    "Rohan",
    "Abigail",
    "Connor",
    "Leila",
    "Jacob",
    "Freya",
    "Dylan",
    "Amara",
    "Nathan",
    "Isla",
    "Kieran",
    "Zoe",
    "Adam",
    "Chloe",
    "Ravi",
    "Ellie",
    "Gareth",
    "Naomi",
    "Lewis",
    "Imogen",
    "Samir",
    "Holly",
    "Ryan",
    "Bethany",
    "Declan",
    "Maya",
    "Scott",
    "Erin",
    "Tariq",
    "Lucy",
    "Aidan",
    "Rachel",
    "Joel",
    "Tessa",
    "Victor",
]
LAST_EN = [
    "Whitfield",
    "Barlow",
    "Okafor",
    "Hensley",
    "Marsh",
    "Pemberton",
    "Doyle",
    "Ashworth",
    "Kaur",
    "Thornton",
    "Fairbanks",
    "Greaves",
    "Holloway",
    "Ibrahim",
    "Jarvis",
    "Kendrick",
    "Lockwood",
    "Merritt",
    "Naylor",
    "Osborne",
    "Prescott",
    "Quigley",
    "Radcliffe",
    "Sandhu",
    "Tennant",
    "Underhill",
    "Vaughan",
    "Winslow",
    "Yates",
    "Zielinski",
    "Abara",
    "Brennan",
    "Chowdhury",
    "Dempsey",
    "Eastwick",
    "Finnegan",
    "Gallagher",
    "Hartley",
    "Ingram",
    "Joshi",
    "Kowalski",
    "Langford",
    "Mistry",
    "Norwood",
    "Oyelaran",
    "Pritchard",
    "Rowntree",
    "Stanhope",
]

SECTORS = [
    ("cabinet d'expertise comptable", "accounting firm", ("Audit", "Advisory")),
    ("PME industrielle de mécanique de précision", "precision engineering manufacturer", ("Industrie", "Engineering")),
    ("agence de communication", "communications agency", ("Studio", "Studio")),
    ("société de transport et logistique", "freight and logistics company", ("Logistique", "Logistics")),
    ("éditeur de logiciels B2B", "B2B software vendor", ("Software", "Software")),
    ("cabinet d'avocats", "law firm", ("Avocats", "Legal")),
    ("entreprise de bâtiment et travaux publics", "construction company", ("Construction", "Construction")),
    ("grossiste alimentaire", "food wholesaler", ("Distribution", "Foods")),
    ("clinique vétérinaire multi-sites", "multi-site veterinary practice", ("Santé", "Care")),
    ("bailleur social", "housing association", ("Habitat", "Housing")),
    ("collectivité territoriale", "local council", ("Agglomération", "Borough Services")),
    ("mutuelle santé", "health insurer", ("Mutuelle", "Mutual")),
    ("agence immobilière", "estate agency", ("Immobilier", "Property")),
    ("bureau d'études en ingénierie", "engineering consultancy", ("Ingénierie", "Consulting")),
    ("réseau de boulangeries", "bakery chain", ("Fournils", "Bakeries")),
    ("organisme de formation professionnelle", "professional training provider", ("Formation", "Learning")),
    ("association d'aide à domicile", "home-care charity", ("Services", "Care Services")),
    ("laboratoire d'analyses", "testing laboratory", ("Laboratoires", "Labs")),
    ("enseigne de magasins de sport", "sports retail chain", ("Sport", "Sports")),
    ("coopérative agricole", "farming cooperative", ("Coopérative", "Growers")),
    ("société de maintenance informatique", "IT services company", ("Services IT", "IT Services")),
    ("hôtel-restaurant indépendant", "independent hotel and restaurant", ("Hôtels", "Hotels")),
    ("fabricant de mobilier de bureau", "office furniture maker", ("Mobilier", "Furniture")),
    ("start-up de la fintech", "fintech start-up", ("Finance", "Pay")),
    ("cabinet de recrutement", "recruitment agency", ("Talents", "Talent")),
    ("entreprise de nettoyage industriel", "industrial cleaning company", ("Propreté", "Facilities")),
    ("société d'énergie renouvelable", "renewable energy company", ("Énergies", "Energy")),
    ("agence de voyages d'affaires", "business travel agency", ("Voyages", "Travel")),
    ("imprimerie", "printing company", ("Impressions", "Print")),
    ("centre hospitalier", "hospital trust", ("Hôpitaux", "Health")),
    ("école de commerce", "business school", ("Campus", "School")),
    ("négoce de matériaux", "building materials merchant", ("Matériaux", "Supplies")),
]
SIZES = [(3, 9), (10, 24), (25, 49), (50, 120), (121, 249), (250, 600), (601, 2400)]
ROLES = [
    ("assistante de direction", "executive assistant"),
    ("responsable comptable", "accounting manager"),
    ("chargé de clientèle", "account manager"),
    ("responsable RH", "HR manager"),
    ("chef de projet", "project manager"),
    ("directrice commerciale", "sales director"),
    ("office manager", "office manager"),
    ("acheteur", "buyer"),
    ("responsable logistique", "logistics manager"),
    ("gérant", "managing director"),
    ("contrôleuse de gestion", "financial controller"),
    ("responsable qualité", "quality manager"),
    ("technicien support", "support technician"),
    ("chargée de communication", "communications officer"),
    ("responsable d'agence", "branch manager"),
    ("juriste", "in-house lawyer"),
    ("chargé de recrutement", "recruiter"),
    ("responsable informatique", "IT manager"),
    ("assistant administratif", "administrative assistant"),
    ("directeur des opérations", "operations director"),
    ("responsable marketing", "marketing manager"),
    ("cheffe d'équipe production", "production team leader"),
    ("chargé d'affaires", "business developer"),
    ("responsable service client", "customer service manager"),
    ("stagiaire en gestion", "business intern"),
    ("responsable formation", "training manager"),
    ("secrétaire générale", "company secretary"),
    ("commercial terrain", "field sales rep"),
]
USER_STYLES = [
    ("terse", "very short, almost telegraphic; no greeting"),
    ("sloppy", "typed fast: lower case, one or two typos or missing accents, abbreviations"),
    ("polite", "polite and complete, with a greeting"),
    ("dump", "pastes the facts as a rough list, then one line saying what is wanted"),
    ("context_first", "explains the context in two or three sentences before the request"),
    ("hurried", "in a hurry, says it is urgent, incomplete sentences"),
    ("precise", "precise and structured, states the expected format"),
    ("spoken", "written the way people talk (dictated), slightly rambling"),
]
MONTHS = [
    ("janvier", "January"),
    ("février", "February"),
    ("mars", "March"),
    ("avril", "April"),
    ("mai", "May"),
    ("juin", "June"),
    ("juillet", "July"),
    ("août", "August"),
    ("septembre", "September"),
    ("octobre", "October"),
    ("novembre", "November"),
    ("décembre", "December"),
]
DAYS = [
    ("lundi", "Monday"),
    ("mardi", "Tuesday"),
    ("mercredi", "Wednesday"),
    ("jeudi", "Thursday"),
    ("vendredi", "Friday"),
]
PRODUCT_WORDS = [
    "Flow",
    "Desk",
    "Pilot",
    "Sync",
    "Plan",
    "Track",
    "Hub",
    "Link",
    "Board",
    "Note",
    "Stock",
    "Paie",
    "Gest",
    "Doc",
]

COMPANY_SYSTEM = {
    "fr": [
        "Tu es Bird, l'assistant de travail de {c} ({sector}). Reste sobre et précis.",
        "Tu es Bird, déployé auprès des équipes de {c}. Tu aides à rédiger, résumer et préparer des documents.",
        "Bird, assistant interne de {c}. Réponses courtes, factuelles, dans la langue de l'utilisateur.",
        "Vous êtes Bird, l'assistant mis à disposition des collaborateurs de {c}. Allez à l'essentiel.",
        "Tu es Bird. Tu travailles pour {c}, {sector}. Dis-le quand une information te manque.",
    ],
    "en": [
        "You are Bird, the work assistant at {c} ({sector}). Stay concise and precise.",
        "You are Bird, deployed for the teams at {c}. You help draft, summarise and prepare documents.",
        "Bird, internal assistant at {c}. Short, factual answers in the user's language.",
        "You are Bird, the assistant available to {c} staff. Get to the point.",
        "You are Bird. You work for {c}, a {sector}. Say so when a piece of information is missing.",
    ],
}
DEFAULT_SYSTEM = {
    "fr": "Tu es Bird, l'assistant de travail conçu par Bird Models. Tu es sobre, franc et pragmatique : tu vas droit au but, "
    "tu dis quand tu ne sais pas, et tu réponds dans la langue de l'utilisateur.",
    "en": "You are Bird, the work assistant built by Bird Models. You are concise, candid and pragmatic: you get to the point, "
    "you say when you don't know, and you answer in the user's language.",
}


def _li(lang: str) -> int:
    return 0 if lang == "fr" else 1


def _weighted(rng: random.Random, pairs) -> str:
    x, acc = rng.random(), 0.0
    for name, w in pairs:
        acc += w
        if x < acc:
            return name
    return pairs[-1][0]


def stem(rng: random.Random) -> str:
    while True:
        s = rng.choice(_S1) + rng.choice(_S2)
        if not any(b in s.lower() for b in _NAME_BLOCK):
            return s


def slug(name: str) -> str:
    table = str.maketrans("éèêëàâäîïôöùûüçÉ", "eeeeaaaiioouuucE")
    return (
        "".join(c for c in name.translate(table).lower().replace("&", " ").replace(" ", "-") if c.isalnum() or c == "-")
        .strip("-")
        .replace("--", "-")
    )


def company(rng: random.Random, lang: str) -> dict:
    sec = rng.choice(SECTORS)
    li = _li(lang)
    name = rng.choice(_FORMS)[li].format(s=stem(rng), tag=sec[2][li])
    lo, hi = rng.choice(SIZES)
    tld = ".fr" if lang == "fr" else rng.choice([".co.uk", ".com", ".com", ".ie"])
    return {"name": name, "sector": sec[li], "staff": rng.randint(lo, hi), "domain": slug(name) + tld}


def person(rng: random.Random, lang: str) -> str:
    return (
        f"{rng.choice(FIRST_FR)} {rng.choice(LAST_FR)}"
        if lang == "fr"
        else f"{rng.choice(FIRST_EN)} {rng.choice(LAST_EN)}"
    )


def people(rng: random.Random, lang: str, n: int) -> list[str]:
    out: list[str] = []
    while len(out) < n:
        p = person(rng, lang)
        if all(p.split()[0] != q.split()[0] and p.split()[-1] != q.split()[-1] for q in out):
            out.append(p)
    return out


def email_of(name: str, domain: str) -> str:
    first, last = name.split()[0], name.split()[-1]
    return f"{slug(first)}.{slug(last)}@{domain}"


def date(rng: random.Random, lang: str, weekday: bool = False) -> str:
    d, m = rng.randint(1, 28), rng.choice(MONTHS)[_li(lang)]
    s = f"{'1er' if d == 1 else d} {m}" if lang == "fr" else f"{d} {m}"
    return f"{rng.choice(DAYS)[_li(lang)]} {s}" if weekday else s


def money(rng: random.Random, lang: str, lo: int, hi: int, step: int = 10) -> str:
    v = rng.randrange(lo, hi, step)
    if lang == "fr":
        return f"{v:,}".replace(",", " ") + " €"
    return f"{rng.choice('£€$')}{v:,}"


def ref(rng: random.Random, prefix: str) -> str:
    return f"{prefix}-{rng.randint(2025, 2026)}-{rng.randint(100, 9899):04d}"


def product(rng: random.Random) -> str:
    return f"{stem(rng)} {rng.choice(PRODUCT_WORDS)}"


# ---------------------------------------------------------------- email pools
EMAIL_SITUATIONS = [
    (
        "relance d'une facture impayée {ref} de {amount}, échue depuis {days} jours",
        "follow-up on unpaid invoice {ref} for {amount}, {days} days overdue",
    ),
    (
        "deuxième relance, plus ferme, pour la facture {ref} ({amount}) restée sans réponse",
        "second, firmer reminder for invoice {ref} ({amount}), no reply so far",
    ),
    (
        "demande de réunion de 45 minutes pour cadrer le projet {product}, créneaux proposés {date} ou {date2}",
        "request for a 45-minute meeting to scope the {product} project, slots offered {date} or {date2}",
    ),
    (
        "envoi d'un devis de {amount} pour {goods}, valable 30 jours",
        "sending a quote of {amount} for {goods}, valid 30 days",
    ),
    ("relance d'un devis envoyé le {date}, resté sans réponse", "chasing a quote sent on {date} that got no answer"),
    (
        "réponse à une réclamation : livraison de {goods} arrivée avec {days} jours de retard",
        "reply to a complaint: delivery of {goods} arrived {days} days late",
    ),
    (
        "excuses après une erreur de facturation de {amount} sur la facture {ref}, avoir en cours",
        "apology after a billing error of {amount} on invoice {ref}, credit note on its way",
    ),
    (
        "annonce interne : nouveaux horaires d'ouverture du site à partir du {date}",
        "internal announcement: new site opening hours from {date}",
    ),
    (
        "annonce interne de l'arrivée de {person} au poste de {role2} le {date}",
        "internal announcement that {person} joins as {role2} on {date}",
    ),
    (
        "refus poli d'une proposition commerciale pour {goods}, sans fermer la porte",
        "polite refusal of a sales proposal for {goods}, leaving the door open",
    ),
    (
        "refus d'une demande de remise de {pct} % formulée par un client",
        "declining a customer's request for a {pct}% discount",
    ),
    (
        "négociation : demander à un fournisseur de ramener sa hausse de prix de {pct} % à la moitié",
        "negotiation: asking a supplier to halve an announced {pct}% price increase",
    ),
    (
        "négociation d'un délai de paiement à 60 jours au lieu de 30 pour une commande de {amount}",
        "negotiating 60-day payment terms instead of 30 on an order worth {amount}",
    ),
    (
        "message d'accueil à une nouvelle recrue ({person}) avec le programme de sa première semaine",
        "welcome message to a new hire ({person}) with the first-week schedule",
    ),
    (
        "convocation à un entretien annuel le {date}, avec la trame à préparer",
        "invitation to an annual review on {date}, with the preparation form",
    ),
    (
        "réponse négative à une candidature après entretien, ton respectueux",
        "rejection after a job interview, respectful tone",
    ),
    (
        "proposition d'embauche à {person} : poste de {role2}, démarrage le {date}",
        "job offer to {person}: {role2} role starting {date}",
    ),
    (
        "rappel au fournisseur : commande {ref} de {goods} toujours pas livrée, attendue le {date}",
        "reminder to a supplier: order {ref} for {goods} still not delivered, was due {date}",
    ),
    (
        "demande de trois références clients à un prestataire avant signature",
        "asking a vendor for three customer references before signing",
    ),
    (
        "annonce d'une coupure du réseau informatique le {date} de 18 h à 20 h",
        "notice of an IT network outage on {date} from 6 pm to 8 pm",
    ),
    (
        "information aux clients : changement de coordonnées bancaires à compter du {date}",
        "notice to customers: new bank details effective {date}",
    ),
    ("demande d'acompte de 30 % sur une commande de {amount}", "request for a 30% deposit on an order worth {amount}"),
    (
        "remerciement à un client après la signature d'un contrat de {amount}",
        "thank-you to a customer after signing a {amount} contract",
    ),
    (
        "signalement d'un retard de {days} jours sur le projet {product}, avec nouveau planning",
        "flagging a {days}-day delay on the {product} project, with a new schedule",
    ),
    (
        "demande de validation d'un budget de {amount} pour {goods}",
        "asking for approval of a {amount} budget for {goods}",
    ),
    (
        "rappel des règles de notes de frais : justificatifs obligatoires, dépôt avant le {date}",
        "reminder of expense rules: receipts mandatory, submission before {date}",
    ),
    (
        "invitation à une formation interne sur {product} le {date}, {pct} places",
        "invitation to an in-house training on {product} on {date}, {pct} seats",
    ),
    (
        "résiliation d'un contrat de {goods} à son échéance du {date}",
        "terminating a {goods} contract at its {date} renewal date",
    ),
    (
        "demande de report d'une échéance de livraison du {date} au {date2}",
        "asking to move a delivery deadline from {date} to {date2}",
    ),
    (
        "transmission d'un dossier à {person} avant un congé, avec les trois points en cours",
        "handover to {person} before leave, with the three open items",
    ),
    (
        "demande d'informations complémentaires avant d'établir un devis pour {goods}",
        "asking for more details before quoting for {goods}",
    ),
    (
        "réponse à un client mécontent du support : ticket ouvert depuis {days} jours",
        "reply to a customer unhappy with support: ticket open for {days} days",
    ),
    (
        "annonce du départ de {person} et de l'organisation transitoire",
        "announcing {person}'s departure and the interim organisation",
    ),
    (
        "demande à l'équipe de saisir ses congés d'été avant le {date}",
        "asking the team to enter summer leave before {date}",
    ),
    (
        "prise de contact avec un prospect rencontré sur un salon, proposition d'échange de 20 minutes",
        "first contact with a prospect met at a trade fair, proposing a 20-minute call",
    ),
    (
        "mise en demeure amiable avant contentieux pour {amount} impayés",
        "final friendly notice before legal action for {amount} unpaid",
    ),
    (
        "information d'une hausse tarifaire de {pct} % au 1er {month}",
        "notice of a {pct}% price increase from 1 {month}",
    ),
    (
        "demande de télétravail exceptionnel la semaine du {date}",
        "request for exceptional remote work the week of {date}",
    ),
    (
        "compte rendu rapide à sa responsable après un rendez-vous client, avec la suite proposée",
        "quick debrief to one's manager after a customer meeting, with the proposed next step",
    ),
    (
        "relance d'un collègue pour des chiffres attendus depuis {days} jours",
        "nudging a colleague for figures expected {days} days ago",
    ),
]
GOODS = [
    ("du mobilier de bureau", "office furniture"),
    ("des licences logicielles", "software licences"),
    ("des fournitures d'emballage", "packaging supplies"),
    ("un contrat de maintenance", "a maintenance contract"),
    ("des prestations de nettoyage", "cleaning services"),
    ("du matériel informatique", "IT equipment"),
    ("une campagne d'affichage", "a poster campaign"),
    ("des pièces usinées", "machined parts"),
    ("un audit de sécurité", "a security audit"),
    ("des formations bureautiques", "office software training"),
    ("un véhicule utilitaire en location", "a leased van"),
    ("des tenues de travail", "workwear"),
    ("des prestations de traduction", "translation services"),
    ("un stand d'exposition", "an exhibition stand"),
    ("des consommables d'impression", "print consumables"),
    ("un service de paie externalisé", "outsourced payroll"),
]
RECIPIENTS = [
    ("un client de longue date", "a long-standing customer"),
    ("un nouveau client", "a new customer"),
    ("un fournisseur", "a supplier"),
    ("toute l'équipe", "the whole team"),
    ("sa responsable hiérarchique", "one's line manager"),
    ("un collègue d'un autre service", "a colleague in another department"),
    ("le service comptabilité d'un client", "a customer's accounts department"),
    ("un prestataire", "a contractor"),
    ("un candidat", "a job applicant"),
    ("un partenaire institutionnel", "a public-sector partner"),
    ("la direction générale", "senior management"),
    ("un prospect", "a prospect"),
    ("un collaborateur de son équipe", "a direct report"),
    ("le propriétaire des locaux", "the landlord"),
]
TONES = [
    ("neutre et professionnel", "neutral and professional"),
    ("cordial", "friendly"),
    ("ferme mais courtois", "firm but courteous"),
    ("formel", "formal"),
    ("direct, sans fioritures", "direct, no frills"),
    ("chaleureux", "warm"),
    ("diplomate", "diplomatic"),
    ("sobre et factuel", "plain and factual"),
    ("rassurant", "reassuring"),
]
EMAIL_CONSTRAINTS = [
    ("moins de 8 lignes", "under 8 lines"),
    ("proposer un appel", "offer a call"),
    ("rappeler la date limite", "restate the deadline"),
    ("mentionner la pièce jointe", "mention the attachment"),
    ("pas de jargon", "no jargon"),
    ("finir par une question précise", "end with one precise question"),
    ("tutoiement entre collègues", "first-name, informal between colleagues"),
    ("deux paragraphes maximum", "two paragraphs at most"),
    ("indiquer qui contacter en cas de question", "say whom to contact with questions"),
    ("une liste à puces pour les points pratiques", "a bullet list for the practical points"),
    ("objet explicite avec la référence", "explicit subject line with the reference"),
    ("aucune", "none"),
    ("aucune", "none"),
]
REPLY_INCOMING = [
    (
        "un client se plaint d'un retard de livraison de {days} jours sur {goods}",
        "a customer complains about a {days}-day late delivery of {goods}",
    ),
    (
        "un fournisseur annonce une hausse de {pct} % au 1er {month}",
        "a supplier announces a {pct}% increase from 1 {month}",
    ),
    (
        "un candidat demande un retour après son entretien du {date}",
        "an applicant asks for feedback after the {date} interview",
    ),
    (
        "un collègue demande les chiffres de {goods} pour le {date}",
        "a colleague asks for the figures on {goods} by {date}",
    ),
    (
        "un client demande une remise de {pct} % pour renouveler son contrat",
        "a customer asks for {pct}% off to renew the contract",
    ),
    ("un partenaire propose une réunion le {date}", "a partner proposes a meeting on {date}"),
    ("un client conteste la facture {ref} de {amount}", "a customer disputes invoice {ref} for {amount}"),
    (
        "un prospect demande des références et une démonstration de {product}",
        "a prospect asks for references and a demo of {product}",
    ),
    (
        "un salarié demande {days} jours de congé à partir du {date}",
        "an employee asks for {days} days of leave from {date}",
    ),
    (
        "la direction demande un point d'avancement sur {product} avant le {date}",
        "management asks for a status update on {product} before {date}",
    ),
    (
        "un utilisateur signale que {product} est inaccessible depuis ce matin",
        "a user reports that {product} has been down since this morning",
    ),
    (
        "un prestataire réclame le paiement de la facture {ref}, échue depuis {days} jours",
        "a contractor chases payment of invoice {ref}, {days} days overdue",
    ),
    (
        "un organisateur invite à intervenir lors d'une table ronde le {date}",
        "an organiser invites the user to speak on a panel on {date}",
    ),
    (
        "un client demande d'avancer la livraison de {goods} au {date}",
        "a customer asks to bring the delivery of {goods} forward to {date}",
    ),
    (
        "un collègue propose de reporter le comité du {date} au {date2}",
        "a colleague suggests moving the committee from {date} to {date2}",
    ),
    (
        "une école demande d'accueillir un stagiaire pendant {days} semaines",
        "a school asks the company to host an intern for {days} weeks",
    ),
    (
        "un fournisseur signale une rupture de stock sur {goods} jusqu'au {date}",
        "a supplier reports {goods} out of stock until {date}",
    ),
    (
        "un client remercie pour la mission et demande un devis pour une suite",
        "a customer says thanks for the work and asks for a quote for a follow-up",
    ),
    (
        "le bailleur annonce des travaux dans l'immeuble du {date} au {date2}",
        "the landlord announces building works from {date} to {date2}",
    ),
    (
        "un commercial externe relance pour la troisième fois sur {goods}",
        "an outside salesperson follows up for the third time about {goods}",
    ),
    (
        "un collègue demande de relire un document de {days} pages pour demain",
        "a colleague asks for a review of a {days}-page document by tomorrow",
    ),
    ("un client demande à résilier son abonnement à {product}", "a customer asks to cancel the {product} subscription"),
    (
        "l'auditeur demande trois pièces justificatives pour la facture {ref}",
        "the auditor asks for three supporting documents for invoice {ref}",
    ),
    (
        "un nouveau collaborateur demande comment se passe sa première journée, le {date}",
        "a new hire asks what the first day, {date}, will look like",
    ),
]
REPLY_INTENTS = [
    ("accepter", "accept"),
    ("refuser poliment", "decline politely"),
    ("demander un délai jusqu'au {date2}", "ask for more time, until {date2}"),
    ("demander des précisions avant de répondre", "ask for details before answering"),
    ("proposer une autre date : {date2}", "propose another date: {date2}"),
    ("accuser réception et dire qu'on revient vers lui sous 48 h", "acknowledge and promise an answer within 48 hours"),
    ("refuser fermement", "refuse firmly"),
    ("accepter à une condition", "accept on one condition"),
    ("s'excuser et proposer un geste commercial", "apologise and offer a goodwill gesture"),
    (
        "transmettre à la bonne personne ({person}) et prévenir l'expéditeur",
        "pass it on to the right person ({person}) and tell the sender",
    ),
    ("accepter en partie seulement", "accept only in part"),
    ("dire non pour l'instant, à revoir dans trois mois", "say not now, revisit in three months"),
    ("répondre factuellement, sans s'engager", "answer factually without committing"),
    ("remercier et confirmer", "thank and confirm"),
]
REWRITE_OPS = [
    ("shorten", "raccourcir de moitié sans perdre l'essentiel", "cut it by half without losing the essentials"),
    ("formal", "rendre plus formel", "make it more formal"),
    ("soften", "adoucir le ton, moins sec", "soften the tone, less curt"),
    ("firmer", "rendre plus ferme", "make it firmer"),
    (
        "fix",
        "corriger l'orthographe et la grammaire sans changer le style",
        "fix spelling and grammar without changing the style",
    ),
    ("translate", "traduire en anglais", "translate into French"),
    ("clarify", "clarifier et structurer", "clarify and structure"),
    ("warmer", "rendre plus chaleureux", "make it warmer"),
    ("simplify", "simplifier pour un lecteur non spécialiste", "simplify for a non-specialist reader"),
    ("neutral", "retirer l'agacement, garder les faits", "take the irritation out, keep the facts"),
]
REWRITE_WEIGHTS = [16, 10, 10, 8, 14, 16, 10, 6, 5, 5]
DRAFT_FLAWS = {
    "shorten": "about twice too long, repeats itself",
    "formal": "too casual for the recipient",
    "soften": "curt, almost rude",
    "firmer": "too apologetic and vague",
    "fix": "5 to 8 spelling or grammar mistakes",
    "translate": "correct but plain",
    "clarify": "confusing order, one long paragraph",
    "warmer": "cold and administrative",
    "simplify": "full of jargon and acronyms",
    "neutral": "visibly irritated, a few sharp remarks",
}

# ---------------------------------------------------------------- meetings, reports, slides
MEETINGS = [
    ("comité de direction", "management committee"),
    ("point hebdomadaire d'équipe", "weekly team meeting"),
    ("réunion de lancement de projet", "project kick-off"),
    ("comité de pilotage", "steering committee"),
    ("réunion de chantier", "site meeting"),
    ("revue de sprint", "sprint review"),
    ("point commercial mensuel", "monthly sales review"),
    ("réunion avec un fournisseur", "supplier meeting"),
    ("rétrospective d'incident", "incident review"),
    ("réunion du CSE", "staff council meeting"),
    ("point budget", "budget review"),
    ("réunion qualité", "quality meeting"),
    ("réunion client de suivi", "customer follow-up meeting"),
    ("atelier de préparation d'un salon", "trade-fair preparation workshop"),
    ("réunion de service", "department meeting"),
    ("point recrutement", "hiring review"),
    ("revue de portefeuille projets", "project portfolio review"),
    ("réunion de coordination inter-sites", "cross-site coordination meeting"),
    ("bilan de fin de mission", "end-of-engagement review"),
    ("point sécurité", "safety meeting"),
    ("réunion de planification trimestrielle", "quarterly planning meeting"),
    ("comité des achats", "purchasing committee"),
]
TOPICS = [
    ("le retard du fournisseur principal", "the main supplier's delay"),
    ("le planning de migration de l'outil de gestion", "the migration schedule for the management tool"),
    ("le budget formation de l'année", "this year's training budget"),
    ("le recrutement de deux profils", "hiring for two roles"),
    ("la baisse du taux de satisfaction", "the drop in satisfaction score"),
    ("l'organisation des astreintes", "the on-call rota"),
    ("le choix d'un nouveau transporteur", "choosing a new carrier"),
    ("la préparation de l'audit", "preparing the audit"),
    ("le déménagement des bureaux", "the office move"),
    ("les impayés de plus de 60 jours", "debts over 60 days"),
    ("la refonte du site web", "the website redesign"),
    ("le plan de charge de l'atelier", "the workshop workload plan"),
    ("la politique de télétravail", "the remote-work policy"),
    ("le renouvellement du parc informatique", "the IT hardware refresh"),
    ("la campagne de rentrée", "the autumn campaign"),
    ("les retours clients sur la nouvelle offre", "customer feedback on the new offer"),
    ("la sécurité sur le quai de chargement", "safety on the loading dock"),
    ("le calendrier de clôture comptable", "the accounting close calendar"),
    ("la hausse des coûts d'énergie", "rising energy costs"),
    ("le tableau de bord mensuel", "the monthly dashboard"),
    ("la gestion des stocks dormants", "handling dead stock"),
    ("la mise à jour des contrats types", "updating the contract templates"),
    ("le support aux heures de pointe", "support at peak hours"),
    ("le partenariat avec une école", "the partnership with a school"),
    ("la journée d'équipe", "the team day"),
    ("le suivi des non-conformités", "tracking non-conformities"),
    ("l'ouverture d'un nouveau site", "opening a new site"),
    ("la tarification de l'an prochain", "next year's pricing"),
    ("la gestion des accès et des mots de passe", "access and password management"),
    ("l'intégration des nouveaux arrivants", "onboarding of new joiners"),
    ("le retard de facturation", "the invoicing backlog"),
    ("le choix d'un outil de signature électronique", "choosing an e-signature tool"),
    ("la réponse à un appel d'offres", "the response to a tender"),
    ("les pannes répétées d'une machine", "a machine's repeated breakdowns"),
    ("la répartition des dossiers", "splitting the caseload"),
    ("le plan de communication interne", "the internal communication plan"),
]
NOTE_STYLES = [
    ("bullets", "telegraphic bullet notes with abbreviations"),
    ("transcript", "rough transcript with speaker first names or initials"),
    ("dictated", "one dictated block, spoken style, little punctuation"),
    ("mixed", "half sentences and arrows (->), a few items out of order"),
    ("chat", "pasted from a chat thread, short lines with first names"),
]
MINUTES_FORMATS = ["headings", "bold", "table"]

DOMAINS = {
    "sales": [
        ("chiffre d'affaires", "revenue", "money"),
        ("nouvelles commandes", "new orders", "count"),
        ("panier moyen", "average order value", "money_s"),
        ("taux de transformation", "conversion rate", "pct"),
        ("nombre de devis émis", "quotes issued", "count"),
        ("clients actifs", "active customers", "count"),
        ("marge brute", "gross margin", "pct"),
        ("part de l'export", "export share", "pct"),
    ],
    "hr": [
        ("effectif", "headcount", "count"),
        ("taux d'absentéisme", "absence rate", "pct_s"),
        ("turnover annuel", "annual staff turnover", "pct"),
        ("postes ouverts", "open positions", "count_s"),
        ("délai moyen de recrutement", "average time to hire", "days"),
        ("heures de formation", "training hours", "count"),
        ("entretiens annuels réalisés", "annual reviews completed", "pct"),
        ("budget formation consommé", "training budget spent", "money"),
    ],
    "support": [
        ("tickets reçus", "tickets received", "count"),
        ("délai moyen de première réponse", "average first-response time", "hours"),
        ("taux de résolution au premier contact", "first-contact resolution rate", "pct"),
        ("satisfaction client", "customer satisfaction", "score"),
        ("tickets en retard", "overdue tickets", "count_s"),
        ("appels décrochés", "calls answered", "pct"),
        ("délai moyen de résolution", "average resolution time", "hours"),
    ],
    "logistics": [
        ("commandes expédiées", "orders shipped", "count"),
        ("taux de livraison à l'heure", "on-time delivery rate", "pct"),
        ("colis endommagés", "damaged parcels", "count_s"),
        ("coût moyen par expédition", "average cost per shipment", "money_s"),
        ("taux de remplissage des camions", "truck fill rate", "pct"),
        ("délai moyen de préparation", "average picking time", "hours"),
        ("retours clients", "customer returns", "count_s"),
        ("stock moyen", "average stock value", "money"),
    ],
    "finance": [
        ("trésorerie disponible", "cash available", "money"),
        ("encours clients", "receivables", "money"),
        ("délai moyen de paiement clients", "average customer payment time", "days"),
        ("charges fixes mensuelles", "monthly fixed costs", "money"),
        ("résultat d'exploitation", "operating profit", "money"),
        ("factures en retard", "overdue invoices", "count_s"),
        ("écart au budget", "budget variance", "pct_s"),
        ("investissements engagés", "capital spending committed", "money"),
    ],
    "project": [
        ("avancement global", "overall progress", "pct"),
        ("jalons tenus", "milestones met", "count_s"),
        ("budget consommé", "budget spent", "money"),
        ("retard cumulé", "cumulative delay", "days"),
        ("anomalies ouvertes", "open defects", "count_s"),
        ("charge restante", "remaining effort", "days"),
        ("utilisateurs formés", "users trained", "count"),
        ("risques majeurs suivis", "major risks tracked", "count_s"),
    ],
    "quality": [
        ("taux de non-conformité", "non-conformity rate", "pct_s"),
        ("réclamations clients", "customer complaints", "count_s"),
        ("audits réalisés", "audits completed", "count_s"),
        ("actions correctives clôturées", "corrective actions closed", "pct"),
        ("taux de rebut", "scrap rate", "pct_s"),
        ("délai moyen de traitement d'une réclamation", "average complaint handling time", "days"),
        ("coût de la non-qualité", "cost of poor quality", "money"),
    ],
    "it": [
        ("disponibilité du système", "system availability", "pct_hi"),
        ("incidents majeurs", "major incidents", "count_s"),
        ("postes renouvelés", "workstations replaced", "count"),
        ("demandes traitées", "requests handled", "count"),
        ("délai moyen de résolution", "average resolution time", "hours"),
        ("comptes inactifs supprimés", "inactive accounts removed", "count"),
        ("budget licences", "licence budget", "money"),
        ("taux de sauvegardes réussies", "backup success rate", "pct_hi"),
    ],
    "marketing": [
        ("visites du site", "website visits", "count_l"),
        ("contacts générés", "leads generated", "count"),
        ("coût par contact", "cost per lead", "money_s"),
        ("taux d'ouverture de la lettre d'information", "newsletter open rate", "pct"),
        ("abonnés", "subscribers", "count_l"),
        ("budget campagne", "campaign budget", "money"),
        ("inscriptions au webinaire", "webinar sign-ups", "count"),
        ("taux de clic", "click-through rate", "pct_s"),
    ],
    "purchasing": [
        ("volume d'achats", "purchasing volume", "money"),
        ("fournisseurs actifs", "active suppliers", "count"),
        ("économies négociées", "negotiated savings", "money"),
        ("commandes en retard", "late purchase orders", "count_s"),
        ("délai moyen d'approvisionnement", "average lead time", "days"),
        ("part des achats sous contrat", "share of spend under contract", "pct"),
        ("litiges fournisseurs", "supplier disputes", "count_s"),
    ],
}
PERIODS = [
    ("T1", "Q1"),
    ("T2", "Q2"),
    ("T3", "Q3"),
    ("T4", "Q4"),
    ("le mois dernier", "last month"),
    ("le premier semestre", "the first half"),
    ("l'année écoulée", "the past year"),
    ("septembre", "September"),
    ("mars", "March"),
    ("la semaine 14", "week 14"),
    ("janvier", "January"),
    ("juin", "June"),
]
DOC_TYPES = [
    ("note de synthèse", "summary memo"),
    ("note interne", "internal memo"),
    ("résumé exécutif", "executive summary"),
    ("rapport court", "short report"),
    ("point de situation", "status note"),
    ("note d'alerte", "alert memo"),
    ("bilan mensuel", "monthly review"),
    ("note pour décision", "decision memo"),
]
AUDIENCES = [
    ("la direction générale", "senior management"),
    ("le comité de direction", "the management committee"),
    ("l'ensemble des salariés", "all staff"),
    ("un client", "a customer"),
    ("le conseil d'administration", "the board"),
    ("les responsables d'équipe", "team leaders"),
    ("un nouveau collaborateur", "a new joiner"),
    ("les commerciaux", "the sales team"),
    ("un partenaire financier", "a financial partner"),
    ("les élus", "elected members"),
    ("l'équipe projet", "the project team"),
    ("les managers de proximité", "line managers"),
]
ANGLES = [
    ("neutral", "factual, no recommendation"),
    ("recommend", "ends with one recommendation that follows from the figures"),
    ("alert", "flags the one figure that should worry the reader"),
    ("progress", "stresses what improved and what did not"),
]
DECK_TOPICS = [
    ("le bilan de {period}", "the {period} review"),
    ("le lancement de l'outil {product}", "the roll-out of {product}"),
    ("l'accueil des nouveaux arrivants", "welcoming new joiners"),
    ("la nouvelle organisation du service", "the department's new organisation"),
    ("les règles de sécurité informatique", "IT security rules"),
    ("l'offre {product} pour un prospect", "the {product} offer for a prospect"),
    ("le plan d'action qualité", "the quality action plan"),
    ("le budget de l'an prochain", "next year's budget"),
    ("les résultats de l'enquête interne", "the staff survey results"),
    ("la procédure de notes de frais", "the expense claim procedure"),
    ("le projet de déménagement", "the office move project"),
    ("la démarche de réduction des déchets", "the waste reduction initiative"),
    ("le retour d'expérience sur un incident", "lessons learned from an incident"),
    ("la présentation de l'entreprise à une école", "presenting the company to a school"),
    ("la feuille de route de {product}", "the {product} roadmap"),
    ("le dispositif de télétravail", "the remote-work scheme"),
    ("la candidature à un appel d'offres", "a bid for a tender"),
    ("le plan de recrutement", "the hiring plan"),
    ("la formation des managers", "manager training"),
    ("le suivi du projet {product}", "progress on the {product} project"),
    ("la politique de déplacements", "the travel policy"),
    ("le partenariat avec {company2}", "the partnership with {company2}"),
    ("les priorités commerciales", "sales priorities"),
    ("la gestion des réclamations", "complaint handling"),
    ("le passage à la facture électronique", "the move to e-invoicing"),
    ("la prévention des accidents du travail", "preventing workplace accidents"),
    ("la comparaison de deux fournisseurs", "a comparison of two suppliers"),
    ("le calendrier de clôture", "the closing calendar"),
    ("l'atelier d'idées de l'équipe", "the team's ideas workshop"),
    ("le tableau de bord du service", "the department dashboard"),
]
DECK_PURPOSES = [
    ("informer", "inform"),
    ("convaincre", "convince"),
    ("former", "train"),
    ("rendre compte", "report"),
    ("faire décider", "get a decision"),
]
DECK_HINTS = [
    ("une diapositive de conclusion avec les prochaines étapes", "a closing slide with next steps"),
    ("pas de diapositive de remerciements", "no thank-you slide"),
    ("une diapositive par idée", "one idea per slide"),
    ("ton sobre, sans slogans", "plain tone, no slogans"),
    ("commencer par le message clé", "open with the key message"),
    ("prévoir une diapositive « risques »", "include a 'risks' slide"),
    ("aucune", "none"),
    ("aucune", "none"),
]

# ---------------------------------------------------------------- web research
WEB_KINDS = [
    ("price", "le tarif actuel de la formule {plan} de {product}", "the current price of the {plan} plan of {product}"),
    ("event", "les dates et le lieu du salon {event}", "the dates and venue of the {event} trade show"),
    ("standard", "ce qu'exige le référentiel {norm} sur {theme}", "what the {norm} standard requires on {theme}"),
    ("company", "l'effectif et les implantations de {company2}", "the headcount and locations of {company2}"),
    ("grant", "les conditions d'éligibilité de l'aide {grant}", "the eligibility conditions of the {grant} grant"),
    (
        "compare",
        "les différences entre {product} et {product2} pour {theme}",
        "the differences between {product} and {product2} for {theme}",
    ),
    ("release", "les nouveautés de la version {ver} de {product}", "what is new in version {ver} of {product}"),
    (
        "supplier",
        "des fournisseurs de {goods} qui livrent en moins de {n} jours",
        "suppliers of {goods} that deliver in under {n} days",
    ),
    (
        "survey",
        "les résultats du dernier baromètre {institute} sur {theme}",
        "the results of the latest {institute} survey on {theme}",
    ),
    (
        "venue",
        "la capacité et les tarifs du centre de congrès {venue}",
        "the capacity and rates of the {venue} conference centre",
    ),
    (
        "cert",
        "les étapes et la durée pour obtenir la certification {norm}",
        "the steps and time needed to get {norm} certification",
    ),
    (
        "deadline",
        "la date limite de dépôt pour l'appel à projets {grant}",
        "the submission deadline for the {grant} call for projects",
    ),
    (
        "carrier",
        "la grille tarifaire du transporteur {company2} pour les colis de moins de {n} kg",
        "the rate card of carrier {company2} for parcels under {n} kg",
    ),
    ("reviews", "les avis d'utilisateurs sur {product}", "user reviews of {product}"),
    (
        "training",
        "les prochaines sessions de la formation « {theme} » chez {company2}",
        "the next sessions of the '{theme}' course at {company2}",
    ),
    (
        "salary",
        "la fourchette de salaire d'un poste de {role2} selon l'étude {institute}",
        "the salary range for a {role2} according to the {institute} study",
    ),
    (
        "outage",
        "si {product} a connu une panne cette semaine et ce que dit l'éditeur",
        "whether {product} had an outage this week and what the vendor says",
    ),
    (
        "merger",
        "ce que l'on sait du rachat de {company2} par {company3}",
        "what is known about the acquisition of {company2} by {company3}",
    ),
]
WEB_THEMES = [
    ("la conservation des documents", "document retention"),
    ("le télétravail", "remote work"),
    ("la gestion de projet", "project management"),
    ("la facturation", "invoicing"),
    ("la qualité de l'air dans les bureaux", "office air quality"),
    ("la sécurité des données", "data security"),
    ("l'accueil du public", "front-desk service"),
    ("le tri des déchets", "waste sorting"),
    ("les délais de paiement", "payment times"),
    ("la prise de parole en public", "public speaking"),
    ("la paie", "payroll"),
    ("le suivi du temps de travail", "time tracking"),
    ("la relation client", "customer relations"),
    ("les achats responsables", "responsible purchasing"),
]
WEB_FLAVORS = (("answer", 0.55), ("read", 0.20), ("not_found", 0.15), ("error_retry", 0.10))
WEB_ERRORS = [
    ("timeout", "The search timed out after 10 s."),
    ("rate_limit", "Rate limit reached, try again."),
    ("empty", ""),
    ("unavailable", "Search service temporarily unavailable."),
]
ANSWER_SHAPES = [
    ("a short paragraph", 3),
    ("2 to 4 bullets", 2),
    ("one sentence with the key fact, then one line of context", 2),
    ("a small comparison (bullets)", 1),
]
PLANS = ["Essentiel", "Pro", "Équipe", "Business", "Starter", "Premium"]

# ---------------------------------------------------------------- tool routing
ROUTE_TOOLS = (
    ("none", 0.30),
    ("read_file", 0.12),
    ("draft_email", 0.12),
    ("run_python", 0.10),
    ("make_document", 0.09),
    ("make_sheet", 0.09),
    ("web_search", 0.08),
    ("read_page", 0.06),
    ("make_slides", 0.04),
)
ROUTE_INTENTS = {
    "web_search": [
        (
            "une information qui change souvent (prix, taux, date d'un événement) sur {subject}",
            "something that changes often (price, rate, event date) about {subject}",
        ),
        ("l'actualité récente de {subject}", "recent news about {subject}"),
        (
            "vérifier en ligne un fait dont l'utilisateur doute sur {subject}",
            "checking online a fact the user doubts about {subject}",
        ),
        ("trouver les coordonnées ou le site de {subject}", "finding the contact details or website of {subject}"),
    ],
    "read_page": [
        ("résumer la page {url}", "summarising the page {url}"),
        ("extraire les prix listés sur {url}", "extracting the prices listed at {url}"),
        ("dire ce que {url} annonce sur {theme}", "saying what {url} states about {theme}"),
        ("vérifier si {url} mentionne une date limite", "checking whether {url} mentions a deadline"),
    ],
    "read_file": [
        ("résumer le fichier {path}", "summarising the file {path}"),
        ("retrouver une clause ou un chiffre précis dans {path}", "finding a specific clause or figure in {path}"),
        ("lister les actions décidées dans {path}", "listing the actions decided in {path}"),
        ("dire quel est le total ou le meilleur mois dans {path}", "telling the total or the best month in {path}"),
        (
            "comparer le contenu de {path} avec ce que l'utilisateur affirme",
            "comparing what {path} says with what the user claims",
        ),
        ("extraire les échéances de {path}", "extracting the deadlines from {path}"),
    ],
    "draft_email": [
        ("préparer un mail à {email} : {topic}", "preparing an email to {email}: {topic}"),
        ("un mail à {email} et {email2} : {topic}", "an email to {email} and {email2}: {topic}"),
        ("répondre à {email} pour {topic}", "replying to {email} to cover: {topic}"),
    ],
    "make_document": [
        (
            "créer un document « {title} » avec {n} sections dont le contenu est donné",
            "creating a document '{title}' with {n} sections whose content is given",
        ),
        (
            "mettre en forme en document des notes collées dans le message ({topic})",
            "turning notes pasted in the message ({topic}) into a document",
        ),
        ("rédiger une procédure courte : {topic}", "writing a short procedure: {topic}"),
    ],
    "make_sheet": [
        (
            "créer un tableur avec {n} colonnes et les lignes données dans le message ({topic})",
            "creating a spreadsheet with {n} columns and the rows given in the message ({topic})",
        ),
        ("transformer une liste collée en tableau ({topic})", "turning a pasted list into a table ({topic})"),
    ],
    "run_python": [
        (
            "calculer moyenne, médiane et écart-type d'une série de {n2} valeurs données",
            "computing mean, median and standard deviation of a series of {n2} given values",
        ),
        (
            "simuler un échéancier ou des intérêts composés sur {n} ans",
            "simulating a repayment schedule or compound interest over {n} years",
        ),
        ("estimer une probabilité par simulation", "estimating a probability by simulation"),
        (
            "agréger des montants par catégorie à partir d'une liste collée",
            "aggregating amounts by category from a pasted list",
        ),
        (
            "calculer une croissance annuelle moyenne sur {n} périodes",
            "computing an average annual growth rate over {n} periods",
        ),
        (
            "trouver les valeurs aberrantes d'une série de {n2} mesures",
            "finding the outliers in a series of {n2} measurements",
        ),
    ],
    "make_slides": [("une présentation de {n} diapositives sur {topic}", "a {n}-slide deck about {topic}")],
}
ROUTE_NONE = [
    (
        "mental",
        "un calcul simple faisable de tête (pourcentage, TVA, règle de trois)",
        "a simple calculation doable mentally (percentage, VAT, rule of three)",
    ),
    (
        "concept",
        "expliquer une notion de gestion ou de bureautique en deux ou trois phrases",
        "explaining a business or office concept in two or three sentences",
    ),
    (
        "rephrase",
        "reformuler ou corriger une phrase collée dans le message",
        "rephrasing or fixing a sentence pasted in the message",
    ),
    ("translate", "traduire une ou deux phrases données", "translating one or two given sentences"),
    (
        "advice",
        "un conseil pratique de travail (organisation, réunion, priorités)",
        "practical work advice (organisation, meetings, priorities)",
    ),
    ("smalltalk", "un bonjour, un merci ou une question légère", "a hello, a thank-you or a light question"),
    (
        "missing",
        "une demande qui semble appeler un outil mais où il manque l'information indispensable (pas de fichier, pas d'adresse, pas de données) : Bird pose UNE question courte",
        "a request that seems to need a tool but lacks the essential input (no file, no address, no data): Bird asks ONE short question",
    ),
    (
        "cannot",
        "une action hors de portée des outils (envoyer réellement un mail, téléphoner, réserver une salle) : Bird le dit et propose ce qu'il peut faire",
        "an action no tool can do (actually sending an email, phoning, booking a room): Bird says so and offers what it can do",
    ),
    (
        "inline",
        "résumer ou analyser un court texte collé dans le message, sans fichier",
        "summarising or analysing a short text pasted in the message, no file involved",
    ),
    (
        "stable_fact",
        "un fait stable et bien connu qui ne demande aucune recherche",
        "a stable, well-known fact that needs no search",
    ),
]
FILE_DIRS = [
    "/partage",
    "/documents",
    "/projets",
    "/clients",
    "/rh",
    "/compta",
    "/shared",
    "/reports",
    "/data",
    "/team",
    "/archive",
    "/exports",
]
FILE_NAMES = [
    ("contrat_{s}", "agreement_{s}", ".docx"),
    ("rapport_{m}", "report_{m}", ".pdf"),
    ("ventes_{y}", "sales_{y}", ".csv"),
    ("cr_reunion_{d}_{m}", "minutes_{d}_{m}", ".md"),
    ("budget_{y}", "budget_{y}", ".xlsx"),
    ("devis_{s}", "quote_{s}", ".pdf"),
    ("planning_{m}", "schedule_{m}", ".xlsx"),
    ("notes_{s}", "notes_{s}", ".txt"),
    ("factures_{m}_{y}", "invoices_{m}_{y}", ".csv"),
    ("procedure_{s}", "procedure_{s}", ".docx"),
    ("inventaire_{y}", "inventory_{y}", ".xlsx"),
    ("offre_{s}", "proposal_{s}", ".pdf"),
]

# ---------------------------------------------------------------- spreadsheets
SHEET_TABLES = [
    (
        [
            ("Date", "Date"),
            ("Client", "Customer"),
            ("Produit", "Product"),
            ("Quantité", "Quantity"),
            ("Prix unitaire", "Unit price"),
            ("Montant", "Amount"),
        ],
        ("ventes", "sales"),
    ),
    (
        [
            ("Nom", "Name"),
            ("Service", "Department"),
            ("Date d'entrée", "Start date"),
            ("Salaire", "Salary"),
            ("Site", "Site"),
        ],
        ("salariés", "employees"),
    ),
    (
        [
            ("N° facture", "Invoice no."),
            ("Client", "Customer"),
            ("Date d'émission", "Issue date"),
            ("Échéance", "Due date"),
            ("Montant TTC", "Total"),
            ("Statut", "Status"),
        ],
        ("factures", "invoices"),
    ),
    (
        [
            ("Référence", "SKU"),
            ("Désignation", "Description"),
            ("Stock", "Stock"),
            ("Seuil", "Reorder level"),
            ("Fournisseur", "Supplier"),
        ],
        ("stock", "inventory"),
    ),
    (
        [
            ("Ticket", "Ticket"),
            ("Ouvert le", "Opened"),
            ("Clos le", "Closed"),
            ("Catégorie", "Category"),
            ("Agent", "Agent"),
            ("Priorité", "Priority"),
        ],
        ("tickets", "tickets"),
    ),
    (
        [("Salarié", "Employee"), ("Début", "Start"), ("Fin", "End"), ("Type", "Type"), ("Validé", "Approved")],
        ("congés", "leave"),
    ),
    ([("Mois", "Month"), ("Budget", "Budget"), ("Réalisé", "Actual"), ("Poste", "Cost line")], ("budget", "budget")),
    (
        [
            ("Commande", "Order"),
            ("Date", "Date"),
            ("Transporteur", "Carrier"),
            ("Poids", "Weight"),
            ("Livré le", "Delivered"),
            ("Région", "Region"),
        ],
        ("expéditions", "shipments"),
    ),
    (
        [
            ("Prospect", "Lead"),
            ("Commercial", "Sales rep"),
            ("Étape", "Stage"),
            ("Montant estimé", "Estimated value"),
            ("Dernier contact", "Last contact"),
        ],
        ("prospects", "pipeline"),
    ),
    (
        [
            ("Tâche", "Task"),
            ("Responsable", "Owner"),
            ("Échéance", "Due date"),
            ("Avancement", "Progress"),
            ("Projet", "Project"),
        ],
        ("tâches", "tasks"),
    ),
    (
        [
            ("Prénom", "First name"),
            ("Nom", "Last name"),
            ("E-mail", "Email"),
            ("Ville", "City"),
            ("Code postal", "Postcode"),
        ],
        ("contacts", "contacts"),
    ),
    (
        [
            ("Date", "Date"),
            ("Salarié", "Employee"),
            ("Catégorie", "Category"),
            ("Montant", "Amount"),
            ("Remboursé", "Reimbursed"),
        ],
        ("notes de frais", "expenses"),
    ),
]
SHEET_NEEDS = [
    (
        "sum_if",
        "additionner une colonne numérique pour une valeur donnée d'une autre colonne",
        "sum a numeric column for a given value in another column",
    ),
    ("sum_ifs", "additionner selon deux critères", "sum on two criteria"),
    ("count_if", "compter les lignes qui ont une valeur donnée", "count the rows with a given value"),
    ("count_ifs", "compter les lignes qui remplissent deux conditions", "count rows meeting two conditions"),
    ("avg_if", "moyenne d'une colonne pour une catégorie", "average of a column for one category"),
    (
        "lookup",
        "retrouver une valeur d'une autre colonne à partir d'un identifiant",
        "look up a value in another column from an identifier",
    ),
    (
        "lookup_safe",
        "recherche avec un texte de remplacement si l'identifiant est absent",
        "lookup with a fallback text when the identifier is missing",
    ),
    (
        "index_match",
        "recherche vers la gauche (la colonne cherchée est à droite du résultat)",
        "left lookup (the search column is to the right of the result)",
    ),
    ("if_tiers", "afficher un libellé selon deux seuils", "show a label depending on two thresholds"),
    (
        "if_flag",
        "afficher un texte si une condition est remplie, sinon rien",
        "show a text when a condition is met, otherwise nothing",
    ),
    (
        "pct_change",
        "variation en pourcentage entre deux colonnes, sans erreur si la base est vide",
        "percentage change between two columns, no error when the base is empty",
    ),
    ("date_diff", "nombre de jours entre deux dates", "number of days between two dates"),
    ("workdays", "nombre de jours ouvrés entre deux dates", "number of working days between two dates"),
    (
        "overdue",
        "signaler les lignes dont la date est dépassée par rapport à aujourd'hui",
        "flag rows whose date is in the past compared with today",
    ),
    ("month_end", "date de fin du mois suivant une date", "end of the month following a date"),
    ("year_month", "extraire l'année ou le mois d'une date", "extract the year or the month from a date"),
    ("concat", "assembler deux colonnes de texte avec un séparateur", "join two text columns with a separator"),
    (
        "left_right",
        "extraire les premiers ou derniers caractères d'une cellule",
        "extract the first or last characters of a cell",
    ),
    (
        "clean",
        "nettoyer les espaces et mettre en majuscules ou en nom propre",
        "trim spaces and convert to upper or proper case",
    ),
    ("rank", "rang d'une valeur dans sa colonne", "rank of a value within its column"),
    (
        "max_min",
        "plus grande ou plus petite valeur d'une colonne, avec condition éventuelle",
        "largest or smallest value in a column, optionally with a condition",
    ),
    ("round", "arrondir un calcul à deux décimales", "round a calculation to two decimals"),
    ("share", "part de chaque ligne dans le total de la colonne", "each row's share of the column total"),
    ("running", "cumul progressif ligne après ligne", "running total row after row"),
    ("unique_count", "compter les valeurs distinctes d'une colonne", "count the distinct values in a column"),
    ("blank", "compter ou repérer les cellules vides", "count or flag empty cells"),
    (
        "sumproduct",
        "total de quantité × prix sans colonne intermédiaire",
        "total of quantity × price without a helper column",
    ),
    ("text_date", "afficher une date sous forme de texte (mois et année)", "show a date as text (month and year)"),
    ("seniority", "ancienneté en années à partir d'une date d'entrée", "seniority in years from a start date"),
    ("and_or", "tester deux conditions à la fois (et / ou)", "test two conditions at once (and / or)"),
    ("top_n", "troisième plus grande valeur d'une colonne", "third largest value in a column"),
    ("median", "médiane d'une colonne", "median of a column"),
]

# ---------------------------------------------------------------- persona chat
PERSONA_KINDS = (
    ("dont_know", 0.16),
    ("false_premise", 0.14),
    ("decline_invent", 0.14),
    ("short_direct", 0.16),
    ("small_talk", 0.12),
    ("candid_opinion", 0.10),
    ("limits", 0.10),
    ("how_to", 0.08),
)
PERSONA_BRIEFS = {
    "dont_know": (
        "The user asks for a fact Bird cannot know: {x}. Bird says so plainly (I don't know / I would need to check / I have no access to that), "
        "says in a few words where to find it, and may offer what it can do instead. No guess dressed up as a fact."
    ),
    "false_premise": "The user's question rests on a false premise: {x}. Bird corrects it politely in one sentence, then answers the real need.",
    "decline_invent": (
        "The user asks Bird to make something up: {x}. Bird declines to invent it, says why in a few words, and offers a concrete alternative "
        "(a placeholder to fill in, a way to get the real figure, a wording without the figure)."
    ),
    "short_direct": "An everyday work question with a clear answer: {x}. Bird answers in one to three sentences, no preamble.",
    "small_talk": "Small talk: {x}. Bird is warm and brief; a light touch or a discreet bird image is allowed here, at most one.",
    "candid_opinion": "The user asks for Bird's honest opinion: {x}. Bird gives a candid, argued view in a few sentences, without flattery, and flags it as its reading.",
    "limits": "The user assumes an ability Bird lacks: {x}. Bird states the limit simply (no memory between conversations / cannot act outside the chat / no web access without a tool) and offers the next best thing.",
    "how_to": "A practical 'how do I' work question: {x}. Bird gives the simplest approach that works, three steps at most, and one concrete next step.",
}
PERSONA_X = {
    "dont_know": [
        ("le chiffre d'affaires exact de son entreprise le mois dernier", "their company's exact revenue last month"),
        (
            "le nom du nouveau directeur d'un concurrent ({company2})",
            "the name of a competitor's new director ({company2})",
        ),
        ("le solde de congés d'un collègue", "a colleague's leave balance"),
        ("la météo de demain pour un déplacement", "tomorrow's weather for a trip"),
        ("le cours de change du jour", "today's exchange rate"),
        ("l'heure de la réunion de jeudi dans son agenda", "the time of Thursday's meeting in their calendar"),
        ("le mot de passe du Wi-Fi invités", "the guest Wi-Fi password"),
        ("si le client {company2} a payé sa dernière facture", "whether customer {company2} paid its last invoice"),
        ("le délai de livraison actuel d'un fournisseur", "a supplier's current delivery time"),
        ("ce qui s'est dit à la réunion d'hier", "what was said in yesterday's meeting"),
        ("le numéro de poste d'une collègue", "a colleague's phone extension"),
        (
            "la date exacte de publication d'un texte réglementaire récent",
            "the exact publication date of a recent regulation",
        ),
        ("le prix actuel d'un billet de train", "the current price of a train ticket"),
        ("le nombre de salariés de {company2}", "how many people work at {company2}"),
    ],
    "false_premise": [
        (
            "augmenter un prix de 20 % puis le baisser de 20 % ramènerait au prix de départ",
            "raising a price by 20% then cutting it by 20% gets back to the starting price",
        ),
        (
            "une marge de 50 % sur le coût serait la même chose qu'une marge de 50 % sur le prix de vente",
            "a 50% markup on cost is the same as a 50% margin on the selling price",
        ),
        (
            "mettre quelqu'un en copie cachée lui permettrait de voir les réponses des autres destinataires",
            "putting someone in BCC lets them see the other recipients' replies",
        ),
        ("la moyenne et la médiane seraient toujours identiques", "the mean and the median are always the same"),
        (
            "supprimer un fichier d'un dossier partagé ne le supprimerait que pour soi",
            "deleting a file from a shared folder only deletes it for oneself",
        ),
        (
            "un pourcentage de pourcentages se calculerait en faisant la moyenne simple des taux",
            "an overall rate is obtained by simply averaging the rates of groups of different sizes",
        ),
        ("12 h 00 PM désignerait minuit", "12:00 PM means midnight"),
        (
            "une corrélation entre deux courbes prouverait que l'une cause l'autre",
            "a correlation between two curves proves one causes the other",
        ),
        (
            "un montant HT se retrouverait en retirant 20 % du TTC",
            "the net amount is found by taking 20% off the gross amount that includes 20% tax",
        ),
        (
            "« répondre à tous » n'enverrait la réponse qu'à l'expéditeur",
            "'reply all' only sends the answer to the sender",
        ),
        (
            "un mot de passe long mais simple serait forcément moins sûr qu'un mot de passe court et compliqué",
            "a long simple passphrase is necessarily weaker than a short complicated password",
        ),
        (
            "trier une seule colonne d'un tableau garderait les lignes alignées",
            "sorting a single column of a table keeps the rows aligned",
        ),
        (
            "une croissance de 10 % par an pendant deux ans ferait exactement 20 %",
            "10% growth a year for two years makes exactly 20%",
        ),
        ("un PDF ne pourrait jamais être modifié", "a PDF can never be edited"),
        ("un fichier CSV conserverait les formules et la mise en forme", "a CSV file keeps formulas and formatting"),
        ("« semestriel » voudrait dire tous les deux ans", "'biannual' and 'biennial' mean the same thing"),
        (
            "un accusé de lecture prouverait que le destinataire a lu le message",
            "a read receipt proves the recipient actually read the message",
        ),
        ("deux remises successives de 10 % feraient 20 %", "two successive 10% discounts add up to 20%"),
        ("Bird se souviendrait de la conversation de la semaine dernière", "Bird remembers last week's conversation"),
        (
            "un petit modèle ne pourrait pas rédiger un compte rendu correct",
            "a small model cannot write decent minutes",
        ),
    ],
    "decline_invent": [
        (
            "une statistique sectorielle « qui fait sérieux » pour une présentation",
            "an industry statistic 'that sounds serious' for a deck",
        ),
        (
            "une citation d'un dirigeant connu pour ouvrir un discours",
            "a quote from a famous executive to open a speech",
        ),
        (
            "un chiffre de satisfaction client pour un rapport, faute de mesure",
            "a customer satisfaction figure for a report, since none was measured",
        ),
        ("une source à citer pour appuyer une affirmation", "a source to cite to back up a claim"),
        ("un témoignage client fictif à présenter comme réel", "a made-up customer testimonial to present as real"),
        ("le montant probable d'un devis concurrent", "the likely amount of a competitor's quote"),
        (
            "une date de livraison à annoncer sans l'avoir confirmée",
            "a delivery date to announce without having confirmed it",
        ),
        ("un numéro d'article de loi pour un courrier", "a legal article number for a letter"),
        ("des résultats d'enquête interne qui n'a pas eu lieu", "results of a staff survey that never took place"),
        ("le taux de croissance du marché pour un plan d'affaires", "the market growth rate for a business plan"),
        (
            "le nombre de participants attendus à un événement, à mettre dans un communiqué",
            "the expected attendance of an event, for a press release",
        ),
        ("des références clients que l'entreprise n'a pas", "customer references the company does not have"),
    ],
    "short_direct": [
        ("la différence entre Cc et Cci", "the difference between CC and BCC"),
        ("que mettre dans l'objet d'un mail de relance", "what to put in the subject of a reminder email"),
        ("à quoi sert un ordre du jour", "what an agenda is for"),
        ("combien de temps prévoir pour une réunion de décision", "how long to plan for a decision meeting"),
        ("la différence entre un acompte et des arrhes", "the difference between a deposit and an instalment"),
        ("comment nommer un fichier pour le retrouver", "how to name a file so it can be found"),
        (
            "faut-il écrire « Madame, Monsieur » ou « Bonjour » à un inconnu",
            "whether to open with 'Dear Sir or Madam' or 'Hello' to a stranger",
        ),
        ("ce qu'est un tableau croisé dynamique", "what a pivot table is"),
        ("la différence entre objectif et indicateur", "the difference between a target and an indicator"),
        ("quand utiliser un graphique en barres plutôt qu'une courbe", "when to use a bar chart rather than a line"),
        ("ce que veut dire « RACI »", "what 'RACI' means"),
        ("la différence entre budget et prévisionnel", "the difference between a budget and a forecast"),
        ("comment conclure un mail à un client", "how to close an email to a customer"),
        ("ce qu'est un jalon dans un projet", "what a milestone is in a project"),
        ("à quoi sert un compte rendu si tout le monde était présent", "what minutes are for if everyone attended"),
        ("la différence entre marge et taux de marque", "the difference between margin and markup"),
    ],
    "small_talk": [
        ("un bonjour du lundi matin", "a Monday-morning hello"),
        ("un merci après un travail utile", "a thank-you after useful work"),
        ("« ça va ? »", "'how are you?'"),
        ("une plainte amusée sur le nombre de réunions", "an amused complaint about too many meetings"),
        ("« bon week-end »", "'have a good weekend'"),
        ("pourquoi il s'appelle Bird", "why it is called Bird"),
        ("une demande de blague courte de bureau", "a request for a short office joke"),
        ("« tu ne te fatigues jamais ? »", "'do you ever get tired?'"),
        ("un au revoir en fin de journée", "a goodbye at the end of the day"),
        ("l'utilisateur annonce qu'il a enfin vidé sa boîte mail", "the user announces an empty inbox at last"),
        ("l'utilisateur s'excuse de poser beaucoup de questions", "the user apologises for asking many questions"),
        ("« tu es toujours aussi bref ? »", "'are you always this brief?'"),
    ],
    "candid_opinion": [
        ("un objet de mail trop long collé dans le message", "an over-long email subject pasted in the message"),
        (
            "un slogan interne un peu creux collé dans le message",
            "a rather hollow internal slogan pasted in the message",
        ),
        ("l'idée d'une réunion quotidienne d'une heure", "the idea of a one-hour daily meeting"),
        ("un plan de présentation en 25 diapositives pour 10 minutes", "a 25-slide outline for a 10-minute talk"),
        ("l'idée d'envoyer une relance le vendredi à 18 h", "the idea of sending a reminder on Friday at 6 pm"),
        ("une phrase d'accroche très flatteuse pour un client", "a very flattering opening line for a customer"),
        ("le choix de tout mettre dans un seul tableau de 40 colonnes", "putting everything in one 40-column table"),
        ("l'idée de répondre à chaud à un mail agressif", "answering an aggressive email on the spot"),
        (
            "un paragraphe de rapport plein de superlatifs collé dans le message",
            "a report paragraph full of superlatives pasted in the message",
        ),
        (
            "s'il vaut mieux un gros modèle d'IA pour rédiger des mails",
            "whether a big AI model is better for writing emails",
        ),
    ],
    "limits": [
        ("se souvenir d'une préférence pour la prochaine fois", "remembering a preference for next time"),
        ("envoyer lui-même le mail", "sending the email itself"),
        ("appeler un fournisseur", "phoning a supplier"),
        ("ouvrir un fichier qui n'a pas été fourni", "opening a file that was not provided"),
        ("regarder sur internet alors qu'aucun outil n'est disponible", "looking online although no tool is available"),
        ("reprendre le document « d'hier »", "picking up 'yesterday's' document"),
        ("réserver une salle de réunion", "booking a meeting room"),
        ("surveiller une boîte mail et prévenir", "watching an inbox and alerting"),
        ("donner la date et l'heure exactes", "giving the exact date and time"),
        ("ressentir du stress avant une échéance", "feeling stressed before a deadline"),
    ],
    "how_to": [
        (
            "dire non à une demande de dernière minute de son responsable",
            "saying no to a manager's last-minute request",
        ),
        ("raccourcir une réunion hebdomadaire qui déborde", "shortening a weekly meeting that overruns"),
        ("relancer quelqu'un sans paraître insistant", "chasing someone without sounding pushy"),
        ("préparer un entretien avec un client mécontent", "preparing a talk with an unhappy customer"),
        ("prioriser une liste de quinze tâches", "prioritising a list of fifteen tasks"),
        ("annoncer une mauvaise nouvelle à son équipe", "breaking bad news to the team"),
        ("reprendre un dossier laissé par un collègue", "taking over a file left by a colleague"),
        ("rendre un tableau de chiffres lisible", "making a table of figures readable"),
        ("demander un retour sur son travail", "asking for feedback on one's work"),
        ("ranger une boîte mail qui déborde", "taming an overflowing inbox"),
        ("présenter un chiffre décevant en comité", "presenting a disappointing figure to a committee"),
        ("déléguer une tâche sans la reprendre ensuite", "delegating a task without taking it back"),
    ],
}


# ---------------------------------------------------------------- shared context
def _ctx(rng: random.Random, lang: str) -> dict:
    li = _li(lang)
    co = company(rng, lang)
    user = person(rng, lang)
    other, third = people(rng, lang, 2)
    return {
        "co": co,
        "user": user,
        "role": rng.choice(ROLES)[li],
        "person": other,
        "person2": third,
        "role2": rng.choice(ROLES)[li],
        "ref": ref(rng, rng.choice(["FA", "F", "INV", "CMD", "PO", "DV"])),
        "amount": money(rng, lang, 180, 48_000),
        "days": rng.choice([3, 4, 5, 6, 8, 10, 12, 15, 21, 30, 45, 60]),
        "date": date(rng, lang),
        "date2": date(rng, lang, weekday=True),
        "pct": rng.choice([3, 4, 5, 6, 8, 10, 12, 15]),
        "month": rng.choice(MONTHS)[li],
        "product": product(rng),
        "product2": product(rng),
        "goods": rng.choice(GOODS)[li],
        "company2": company(rng, lang)["name"],
        "company3": company(rng, lang)["name"],
    }


def _fill(text: str, c: dict) -> str:
    return text.format(**{k: v for k, v in c.items() if isinstance(v, str | int)})


def _head(c: dict, lang: str, style: tuple, register: str | None) -> list[str]:
    co = c["co"]
    lines = [
        f"Language: {'French' if lang == 'fr' else 'English'}",
        f"User: {c['user']}, {c['role']} at {co['name']} ({co['sector']}, {co['staff']} staff)",
        f"User's writing style: {style[1]}",
    ]
    if register:
        lines.append(f"User addresses Bird with: {register} (Bird mirrors it in its own voice)")
    return lines


def _metric(rng: random.Random, lang: str, m: tuple) -> str:
    li, kind = _li(lang), m[2]
    if kind == "money":
        v = money(rng, lang, 12_000, 2_400_000, 500)
    elif kind == "money_s":
        v = money(rng, lang, 12, 480, 1)
    elif kind == "pct":
        v = f"{rng.randint(11, 94)} %" if lang == "fr" else f"{rng.randint(11, 94)}%"
    elif kind == "pct_s":
        x = f"{rng.randint(1, 9)}.{rng.randint(1, 9)}"
        v = x.replace(".", ",") + " %" if lang == "fr" else x + "%"
    elif kind == "pct_hi":
        x = f"9{rng.randint(5, 9)}.{rng.randint(1, 9)}"
        v = x.replace(".", ",") + " %" if lang == "fr" else x + "%"
    elif kind == "days":
        v = f"{rng.randint(4, 75)} {'jours' if lang == 'fr' else 'days'}"
    elif kind == "hours":
        v = f"{rng.randint(2, 46)} {'heures' if lang == 'fr' else 'hours'}"
    elif kind == "score":
        x = f"{rng.randint(6, 9)}.{rng.randint(0, 9)}"
        v = (x.replace(".", ",") if lang == "fr" else x) + "/10"
    elif kind == "count_s":
        v = str(rng.randint(2, 38))
    elif kind == "count_l":
        v = f"{rng.randrange(4_000, 180_000, 100):,}".replace(",", " " if lang == "fr" else ",")
    else:
        v = f"{rng.randint(41, 4_800):,}".replace(",", " " if lang == "fr" else ",")
    trend = ""
    if rng.random() < 0.45 and kind not in ("score",):
        d = f"{rng.choice('+-')}{rng.randint(1, 24)}"
        trend = f" ({d} % vs période précédente)" if lang == "fr" else f" ({d}% vs previous period)"
    return f"{m[li]} : {v}{trend}" if lang == "fr" else f"{m[li]}: {v}{trend}"


def _facts(rng: random.Random, lang: str, n: int) -> tuple[str, list[str]]:
    dom = rng.choice(list(DOMAINS))
    return dom, [_metric(rng, lang, m) for m in rng.sample(DOMAINS[dom], min(n, len(DOMAINS[dom])))]


# ---------------------------------------------------------------- task samplers: each returns (flags, brief lines)
def _email_write(rng, lang, c):
    li = _li(lang)
    sit = _fill(rng.choice(EMAIL_SITUATIONS)[li], c)
    cons = rng.choice(EMAIL_CONSTRAINTS)[li]
    note = rng.random() < 0.25
    lines = [
        f"Situation: {sit}",
        f"Recipient: {rng.choice(RECIPIENTS)[li]}, named {c['person']} ({c['company2']})",
        f"Tone wanted for the email: {rng.choice(TONES)[li]}",
        f"Constraint stated by the user: {cons}",
        "The user message must contain every fact the email needs (names, amounts, dates, references).",
        f"Bird's one-line note after the email: {'yes, flag one assumption or one thing to check' if note else 'no (leave `note` empty)'}",
    ]
    return {"note": note}, lines


def _email_reply(rng, lang, c):
    li = _li(lang)
    layout = rng.choice(["quote", "sep", "after", "label"])
    lines = [
        f"Incoming email: {_fill(rng.choice(REPLY_INCOMING)[li], c)}; sent by {c['person']} ({c['company2']}), {rng.randint(50, 160)} words, tone: {rng.choice(TONES)[li]}",
        f"User's intent, given in a few words: {_fill(rng.choice(REPLY_INTENTS)[li], c)}",
        f"Tone wanted for the reply: {rng.choice(TONES)[li]}; the reply is signed {c['user']}",
        "`instruction` holds only the user's few words (no pasted email); `incoming_email` holds the full received email.",
    ]
    return {"layout": layout}, lines


def _email_rewrite(rng, lang, c):
    li = _li(lang)
    op = rng.choices(REWRITE_OPS, weights=REWRITE_WEIGHTS)[0]
    answer_lang = ("en" if lang == "fr" else "fr") if op[0] == "translate" else lang
    lines = [
        f"Draft written by the user: an email about {_fill(rng.choice(EMAIL_SITUATIONS)[li], c)}, to {c['person']}; {rng.randint(60, 190)} words; flaw: {DRAFT_FLAWS[op[0]]}",
        f"Operation asked: {op[1 + li]}",
        f"The rewrite is in {'French' if answer_lang == 'fr' else 'English'}; it keeps every fact, name, amount and date of the draft.",
        "`instruction` holds only the user's short request; `draft` holds the pasted draft; `note` stays empty unless one fact of the draft is ambiguous.",
    ]
    return {"op": op[0], "answer_lang": answer_lang, "layout": rng.choice(["quote", "sep", "after", "label"])}, lines


def _meeting_minutes(rng, lang, c):
    li = _li(lang)
    names = [c["user"], *people(rng, lang, rng.randint(2, 5))]
    topics = [t[li] for t in rng.sample(TOPICS, rng.randint(2, 4))]
    style = rng.choice(NOTE_STYLES)
    n_dec, n_act, n_open = rng.randint(1, 3), rng.randint(2, 5), rng.randint(0, 3)
    dated = max(1, n_act - rng.randint(0, 1))
    fmt = rng.choice(MINUTES_FORMATS)
    lines = [
        f"Meeting: {rng.choice(MEETINGS)[li]} on {date(rng, lang, weekday=True)}; present: {', '.join(names)}",
        f"Topics discussed: {'; '.join(topics)}",
        f"Raw notes style: {style[1]}; {rng.randint(130, 320)} words; includes one or two digressions to leave out",
        f"The notes contain {n_dec} decision(s), {n_act} action(s) ({dated} with an explicit date, each with a named owner) and {n_open} open point(s)",
        f"Figures or dates mentioned in the notes: {date(rng, lang)}, {date(rng, lang)}, {money(rng, lang, 500, 90_000, 100)}",
        "The minutes use only what is in the notes: no new figure, date or name. An action without a date in the notes gets an empty `due`.",
    ]
    return {"format": fmt, "layout": rng.choice(["sep", "after", "label"])}, lines


def _report_note(rng, lang, c):
    li = _li(lang)
    dom, facts = _facts(rng, lang, rng.randint(4, 6))
    angle = rng.choice(ANGLES)
    extra = rng.choice(
        [
            ("un fait qualitatif : départ d'un salarié clé", "one qualitative fact: a key employee left"),
            ("un fait qualitatif : nouvel outil déployé", "one qualitative fact: a new tool went live"),
            ("un fait qualitatif : un gros client perdu", "one qualitative fact: a large customer was lost"),
            ("un fait qualitatif : réorganisation en cours", "one qualitative fact: a reorganisation is under way"),
            ("aucun", "none"),
            ("aucun", "none"),
        ]
    )[li]
    lines = [
        f"Document: {rng.choice(DOC_TYPES)[li]} for {rng.choice(AUDIENCES)[li]}, about {dom} over {rng.choice(PERIODS)[li]}",
        "Facts the user supplies (ALL must appear in the user message, in any layout):",
        *[f"  - {f}" for f in facts],
        f"Additional element: {extra}",
        f"Angle: {angle[1]}; length: {rng.choice(['120-180', '180-260', '260-350'])} words",
        "Every number in the document must be copied from the user message. No computed totals, differences or new percentages.",
    ]
    return {"angle": angle[0]}, lines


def _slides(rng, lang, c):
    li = _li(lang)
    n = rng.randint(4, 10)
    c2 = {**c, "period": rng.choice(PERIODS)[li]}
    dom, facts = _facts(rng, lang, rng.randint(0, 4))
    lines = [
        f"Deck about {_fill(rng.choice(DECK_TOPICS)[li], c2)}; audience: {rng.choice(AUDIENCES)[li]}; purpose: {rng.choice(DECK_PURPOSES)[li]}",
        f"Number of slides: exactly {n} ({'stated by the user' if rng.random() < 0.6 else 'not stated by the user; Bird picks it'})",
        f"User's extra wish: {rng.choice(DECK_HINTS)[li]}",
    ]
    if facts:
        lines += ["Figures the user supplies (the only figures allowed in the slides):", *[f"  - {f}" for f in facts]]
    else:
        lines.append(
            "The user supplies no figure: the slides contain no figure either (small counts like 'three steps' are fine)."
        )
    lines.append(f"Other content given by the user: {rng.randint(2, 4)} key points in their own words")
    return {"n_slides": n}, lines


def _web_research(rng, lang, c):
    li = _li(lang)
    kind = rng.choice(WEB_KINDS)
    st = stem(rng)
    c2 = {
        **c,
        "plan": rng.choice(PLANS),
        "event": f"{st}expo {rng.choice([2026, 2027])}",
        "norm": f"{st[:4].upper()}-{rng.randint(100, 990)}",
        "theme": rng.choice(WEB_THEMES)[li],
        "grant": f"{'Tremplin' if lang == 'fr' else 'Springboard'} {st}",
        "ver": f"{rng.randint(2, 9)}.{rng.randint(0, 6)}",
        "n": rng.choice([2, 3, 5, 10, 20, 30]),
        "institute": f"{'Institut' if lang == 'fr' else 'Institute'} {st}",
        "venue": f"{st} {'Congrès' if lang == 'fr' else 'Hall'}",
    }
    flavor = _weighted(rng, WEB_FLAVORS)
    n_results = rng.randint(3, 5)
    err = rng.choice(WEB_ERRORS) if flavor == "error_retry" else None
    lines = [
        f"The user needs: {_fill(kind[1 + li], c2)}",
        "All organisations, products, sites and domains in the results are FICTIONAL (use the names above; invent plausible domains); never a real brand, outlet or person.",
        f"Search results: exactly {n_results}, each with title, URL and a 25-50 word snippet; realistic mix of relevant and less relevant pages",
    ]
    if flavor == "answer":
        lines.append("Case: the snippets contain the answer. Bird answers from them.")
    elif flavor == "read":
        lines.append(
            "Case: the snippets hint at the answer but the detail is in one page. Bird reads that page (`read_index`), whose text (150-300 words) contains the answer."
        )
    elif flavor == "not_found":
        lines.append(
            "Case: the results are on topic but do NOT contain what the user asked (outdated, vague or about something adjacent). Bird says plainly that it did not find the answer, "
            "reports only what the results do say, and proposes one concrete next step. No guessed figure or date."
        )
    else:
        lines.append(
            f"Case: the first search fails ({err[0]}). Bird retries with a clearly reformulated query (`query`), which returns the results; `failed_query` is the first attempt."
        )
    shape = rng.choices(ANSWER_SHAPES, weights=[s[1] for s in ANSWER_SHAPES])[0][0]
    lines.append(
        f"Final answer: {shape}; every fact carries a citation like [2] (the number is the position of the result); no 'Sources' list (it is added automatically)"
    )
    flags = {
        "flavor": flavor,
        "n_results": n_results,
        "max_results": rng.choice([None, None, None, 5, n_results, 8]),
        "tools": "all" if rng.random() < 0.6 else "web",
        "result_format": "json" if rng.random() < 0.7 else "text",
    }
    if err:
        flags["error"] = list(err)
    return flags, lines


def _tool_routing(rng, lang, c):
    li = _li(lang)
    tool = _weighted(rng, ROUTE_TOOLS)
    co = c["co"]
    if tool == "none":
        k = rng.choice(ROUTE_NONE)
        lines = [
            f"Expected behaviour: NO tool call. Request type: {k[1 + li]}",
            f"Subject area for the request: {rng.choice(TOPICS)[li]} / {rng.choice(list(DOMAINS))}",
            "Bird answers directly and briefly (or asks its single question). The eight tools are available but none is needed.",
        ]
        return {"tool": "none", "none_kind": k[0]}, lines
    fn = rng.choice(FILE_NAMES)
    mon = rng.choice(MONTHS)[li][:4].lower().replace("é", "e").replace("û", "u")
    path = f"{rng.choice(FILE_DIRS)}/{fn[li].format(s=slug(stem(rng)), m=mon, y=rng.choice([2025, 2026]), d=rng.randint(1, 28))}{fn[2]}"
    dom2 = slug(c["company2"]) + (".fr" if lang == "fr" else ".com")
    url = f"https://www.{dom2}/{rng.choice(['tarifs', 'actualites', 'offres', 'blog/bilan', 'conditions', 'pricing', 'news', 'guide', 'faq', 'careers'])}"
    c2 = {
        **c,
        "url": url,
        "path": path,
        "email": email_of(c["person"], dom2),
        "email2": email_of(c["person2"], co["domain"]),
        "subject": rng.choice([c["company2"], c["product"], rng.choice(WEB_THEMES)[li]]),
        "theme": rng.choice(WEB_THEMES)[li],
        "topic": rng.choice(TOPICS)[li],
        "title": rng.choice(TOPICS)[li].capitalize(),
        "n": rng.randint(2, 5),
        "n2": rng.randint(8, 16),
    }
    lines = [
        f"Expected behaviour: ONE call to `{tool}`. The user wants: {_fill(rng.choice(ROUTE_INTENTS[tool])[li], c2)}",
        "The user message contains everything the call needs (address, path, URL, data, content); the arguments reuse it exactly.",
        "`arguments` are the arguments of the call, complete and ready to run.",
    ]
    need = {"read_file": path, "read_page": url, "draft_email": c2["email"]}.get(tool)
    return {"tool": tool, "must_contain": need}, lines


def _sheet_formula(rng, lang, c):
    li = _li(lang)
    cols, name = rng.choice(SHEET_TABLES)
    need = rng.choice(SHEET_NEEDS)
    if lang == "fr":
        app, locale = rng.choices(
            [
                ("Excel en français (Excel FR)", "fr"),
                ("Excel en anglais", "en"),
                ("Google Sheets, fonctions en anglais", "en"),
            ],
            weights=[60, 15, 25],
        )[0]
    else:
        app, locale = rng.choices([("Excel", "en"), ("Google Sheets", "en")], weights=[65, 35])[0]
    first = rng.choice([0, 0, 0, 1])
    letters = "ABCDEFGHIJ"[first:]
    layout = ", ".join(f"{letters[i]} = {col[li]}" for i, col in enumerate(cols))
    lines = [
        f"Spreadsheet: {app}; table of {name[li]}, headers in row 1, data in rows 2 to {rng.randint(40, 2400)}; columns: {layout}",
        f"Need: {need[1 + li]}",
        f"Detail to make it concrete: a criterion or cell taken from this context: {c['goods']}, {c['date']}, {c['person'].split()[0]}",
        f"Formula language: {'FRENCH function names and `;` separators' if locale == 'fr' else 'ENGLISH function names and `,` separators'}; well-known functions only",
        "`formula` is a single formula starting with `=`; `explanation` is ONE sentence saying what it does and what to adapt.",
    ]
    return {"locale": locale, "need": need[0], "answer_style": rng.choice(["fence", "inline", "inline"])}, lines


def _persona_chat(rng, lang, c):
    li = _li(lang)
    kind = _weighted(rng, PERSONA_KINDS)
    x = _fill(rng.choice(PERSONA_X[kind])[li], c)
    turns = 2 if rng.random() < 0.2 else 1
    lines = [
        PERSONA_BRIEFS[kind].format(x=x),
        f"Work context to anchor the exchange: {rng.choice(TOPICS)[li]}",
        f"Turns: {turns} ({'the second user turn reacts to the first answer; Bird stays consistent' if turns == 2 else 'single exchange'})",
        f"Length of each Bird answer: {rng.choice(['one or two sentences', 'two or three sentences', 'at most 60 words'])}",
    ]
    return {"kind": kind, "turns": turns}, lines


_SAMPLERS = {
    "email_write": _email_write,
    "email_reply": _email_reply,
    "email_rewrite": _email_rewrite,
    "meeting_minutes": _meeting_minutes,
    "report_note": _report_note,
    "slides": _slides,
    "web_research": _web_research,
    "tool_routing": _tool_routing,
    "sheet_formula": _sheet_formula,
    "persona_chat": _persona_chat,
}


def scenario_id(task: str, index: int) -> str:
    return f"synth-{task}-{index:06d}"


def sample(task: str, index: int, seed: int = 0) -> dict:
    """One scenario, fully determined by (task, index, seed)."""
    rng = random.Random(f"{seed}:{task}:{index}")
    lang = "fr" if rng.random() < FR_SHARE else "en"
    thinking = rng.random() < THINKING[task]
    system = _weighted(rng, SYSTEM_MIX)
    register = None
    if lang == "fr":
        register = "tu" if rng.random() < 0.35 else "vous"
    style = rng.choice(USER_STYLES)
    c = _ctx(rng, lang)
    flags, lines = _SAMPLERS[task](rng, lang, c)
    head = _head(c, lang, style, register)
    if thinking:
        head.append(
            "Reasoning: yes; Bird's reasoning fields hold 1-5 short natural sentences in the user's language (what is asked, what matters, the plan)"
        )
    sc = {
        "id": scenario_id(task, index),
        "task": task,
        "lang": lang,
        "thinking": thinking,
        "system": system,
        "register": register,
        "style": style[0],
        "company": c["co"]["name"],
        "sector": c["co"]["sector"],
        **flags,
    }
    sc["brief"] = "\n".join(head + lines)
    if system == "company":
        sc["system_text"] = rng.choice(COMPANY_SYSTEM[lang]).format(c=c["co"]["name"], sector=c["co"]["sector"])
    elif system == "default":
        sc["system_text"] = DEFAULT_SYSTEM[lang]
    return sc


def plan(
    targets: dict[str, int] | None = None, tasks: list[str] | None = None, limit: int = 0, oversample: float = 2.0
) -> dict[str, dict]:
    """{task: {"target": accepted records wanted, "max_attempts": scenarios we may spend}}.

    `limit` scales every target so that the total is about `limit` (cheap pilot), keeping the task mix.
    """
    targets = dict(targets or TARGETS)
    if tasks:
        targets = {t: targets[t] for t in tasks}
    total = sum(targets.values())
    if limit and limit < total:
        targets = {t: max(1, round(n * limit / total)) for t, n in targets.items()}
    return {t: {"target": n, "max_attempts": int(n * oversample) + 8} for t, n in targets.items()}


def interleave(plan_: dict[str, dict], done: dict[str, int] | None = None):
    """Yield (task, index) so that any prefix keeps the task mix; indices start after `done[task]`."""
    done = done or {}
    keyed = []
    for t, p in plan_.items():
        n = p["max_attempts"]
        keyed += [((i + 0.5) / n, t, i) for i in range(done.get(t, 0), n)]
    for _, t, i in sorted(keyed):
        yield t, i
