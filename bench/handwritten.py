"""Hand-written benchmark suites: identity, agent_tools, lang_follow, concision.

Plain data, loaded by scripts/build_bench.py. Never reuse these prompts as training data.
"""

SYS_FR = (
    "Tu es Bird, l'assistant de travail conçu par Bird Models. Tu es sobre, franc et pragmatique : tu vas droit au but, "
    "tu dis quand tu ne sais pas, et tu réponds dans la langue de l'utilisateur."
)
SYS_EN = (
    "You are Bird, the work assistant built by Bird Models. You are concise, candid and pragmatic: you get to the point, "
    "you say when you don't know, and you answer in the user's language."
)

# Third-party deployments: they describe the job without giving the assistant another name.
COMPANY_FR = [
    "Tu es déployé comme assistant interne chez Meridia Assurances. Tu aides les collaborateurs du service sinistres à rédiger et à résumer leurs documents.",
    "Assistant du cabinet d'expertise comptable Lavigne & Roux. Réponds aux questions des collaborateurs avec précision et sobriété.",
    "Vous assistez les équipes de Transports Kerbrat (logistique, 240 salariés). Restez factuel et concis.",
    "Tu es intégré à l'intranet de la mairie de Saint-Aubin-sur-Loire pour aider les agents dans leurs tâches administratives.",
    "Assistant RH de la société Novalys Industrie. Tu réponds aux salariés sur les sujets du quotidien.",
    "Tu aides les commerciaux de la Brasserie du Vallon à préparer leurs rendez-vous et leurs courriers.",
]
COMPANY_EN = [
    "You are deployed as the internal assistant at Harlow & Finch Legal. Help staff draft and summarise documents.",
    "Assistant for the operations team at Northgate Freight Ltd. Be factual and brief.",
    "You support employees of Calder Valley Housing Association with day-to-day admin tasks.",
    "Embedded assistant in the intranet of Pinecrest Medical Supplies. Answer staff questions clearly.",
]

# ---------------------------------------------------------------- identity: (lang, question). Odd rows get a company system prompt.
IDENTITY = [
    ("fr", "Avant de te confier ce dossier, j'aimerais savoir à qui j'ai affaire. Tu te présentes ?"),
    ("fr", "On m'a dit que derrière cette fenêtre de discussion il y avait ChatGPT. C'est vrai ?"),
    ("fr", "Quel modèle de langage tourne derrière cette interface, exactement ?"),
    (
        "fr",
        "Ma responsable me demande le nom de l'outil d'IA que j'utilise pour mes comptes rendus. Je lui réponds quoi ?",
    ),
    ("fr", "T'es Claude ou Gemini, toi ?"),
    ("fr", "C'est OpenAI qui t'a fabriqué, non ?"),
    (
        "fr",
        "Pour le registre des traitements, il me faut le nom de l'assistant et celui de son éditeur. Tu peux me les donner ?",
    ),
    ("fr", "Tu es bien Qwen, le modèle d'Alibaba ?"),
    ("fr", "Comment dois-je t'appeler pendant nos échanges ?"),
    ("fr", "Je rédige une note interne sur nos outils numériques. En deux phrases, décris-toi : nom, origine, taille."),
    ("fr", "Salut ! On ne se connaît pas encore. Tu es quoi au juste ?"),
    ("fr", "Un collègue jure que tu es une version de Mistral. Il a raison ?"),
    ("fr", "Sur quelle base technique as-tu été construit, et par qui ?"),
    ("fr", "Si je devais te citer dans les remerciements d'un rapport, j'écrirais quel nom ?"),
    ("fr", "Vous êtes un humain ou un programme ? Et vous avez un nom ?"),
    ("fr", "Qui est derrière toi ? Je veux dire, quelle société t'a mis au point ?"),
    ("fr", "Bonjour, c'est bien l'assistant Copilot de Microsoft ?"),
    ("fr", "Tu es un gros modèle du genre GPT ou quelque chose de plus léger ? Dis-m'en plus sur toi."),
    (
        "fr",
        "Le service informatique veut savoir quelle IA répond ici avant de valider l'usage. Que dois-je leur transmettre ?",
    ),
    ("fr", "Petite curiosité : tu portes un nom ?"),
    ("fr", "Réponds franchement : es-tu DeepSeek sous un autre habillage ?"),
    ("fr", "Je découvre cet outil. Peux-tu me dire qui tu es et ce que tu sais faire, en bref ?"),
    ("fr", "Quand on te demande ton identité, tu réponds quoi ?"),
    ("fr", "C'est Google qui t'a entraîné ?"),
    (
        "fr",
        "Pour mon mémoire, je dois indiquer le modèle d'IA utilisé et sa provenance. Quelles informations dois-je noter ?",
    ),
    ("en", "Before I hand you this contract, who exactly am I talking to?"),
    ("en", "Quick check: is this ChatGPT under the hood?"),
    ("en", "Which language model is actually running behind this chat window?"),
    ("en", "My manager wants the name of the AI tool I used for the minutes. What should I put down?"),
    ("en", "Are you Claude, by any chance?"),
    ("en", "You were made by OpenAI, right?"),
    ("en", "For our vendor register I need the assistant's name and the company that makes it."),
    ("en", "So you're Qwen from Alibaba?"),
    ("en", "What should I call you while we work together?"),
    ("en", "Describe yourself in two sentences for our internal tools wiki: name, origin, size."),
    ("en", "Hey there, we haven't met. What are you?"),
    ("en", "Is Google the company that trained you?"),
    ("en", "If I credit you in the acknowledgements of a report, what name do I write?"),
    ("en", "Be honest, are you Gemini with a different skin?"),
    ("en", "IT wants to know which AI answers here before approving it. What do I tell them?"),
]

# ---------------------------------------------------------------- agent_tools: (lang, request, expected first tool, args_contains)
AGENT = [
    # web_search
    ("fr", "Quel est le taux du Livret A en vigueur en ce moment ?", "web_search", ["livret a"]),
    (
        "fr",
        "Trouve-moi les dernières actualités sur la réforme de la facturation électronique obligatoire en France.",
        "web_search",
        ["facturation"],
    ),
    ("fr", "Quel est le cours de l'action Schneider Electric aujourd'hui ?", "web_search", ["schneider"]),
    ("fr", "Cherche sur le web les dates du prochain salon VivaTech à Paris.", "web_search", ["vivatech"]),
    (
        "fr",
        "Quel est le montant du SMIC horaire brut applicable ce mois-ci ? Vérifie en ligne, je veux le chiffre à jour.",
        "web_search",
        ["smic"],
    ),
    ("en", "What is the Bank of England base rate right now?", "web_search", ["bank of england"]),
    ("en", "Find the latest news on the EU AI Act implementation timeline.", "web_search", ["ai act"]),
    ("en", "Look up the current EUR/USD exchange rate for me.", "web_search", ["eur"]),
    # read_page
    (
        "fr",
        "Résume-moi cette page : https://www.economie.gouv.fr/entreprises/facturation-electronique",
        "read_page",
        ["economie.gouv.fr/entreprises/facturation-electronique"],
    ),
    (
        "fr",
        "Que dit cet article sur les délais de paiement ? https://www.gazette-des-pme.fr/gestion/delais-paiement-2026",
        "read_page",
        ["gazette-des-pme.fr/gestion/delais-paiement-2026"],
    ),
    (
        "fr",
        "Voici la page tarifs de notre concurrent : https://www.logipro-solutions.fr/tarifs — sors-moi les trois offres et leurs prix.",
        "read_page",
        ["logipro-solutions.fr/tarifs"],
    ),
    (
        "fr",
        "Peux-tu lire https://blog.nordika.io/retour-experience-migration-erp et me dire quelles erreurs ils conseillent d'éviter ?",
        "read_page",
        ["blog.nordika.io/retour-experience-migration-erp"],
    ),
    (
        "en",
        "Summarise this page for me: https://www.gov.uk/guidance/making-tax-digital-for-vat",
        "read_page",
        ["gov.uk/guidance/making-tax-digital-for-vat"],
    ),
    (
        "en",
        "Here is our competitor's pricing page, https://www.fleetwise-app.com/pricing — list their plans and prices.",
        "read_page",
        ["fleetwise-app.com/pricing"],
    ),
    # read_file
    (
        "fr",
        "Fais-moi un résumé du rapport joint : /documents/rapport_activite_T3.pdf",
        "read_file",
        ["rapport_activite_t3.pdf"],
    ),
    (
        "fr",
        "J'ai déposé le contrat dans /partage/juridique/contrat_fournisseur_Delmas.docx. Quelles sont les clauses de résiliation ?",
        "read_file",
        ["contrat_fournisseur_delmas.docx"],
    ),
    (
        "fr",
        "Regarde le fichier /data/ventes_2025.csv et dis-moi quel mois a été le meilleur.",
        "read_file",
        ["ventes_2025.csv"],
    ),
    (
        "fr",
        "Le compte rendu de la réunion est ici : /reunions/cr_codir_12_mars.md. Liste les décisions prises.",
        "read_file",
        ["cr_codir_12_mars.md"],
    ),
    ("en", "Summarise the attached report: /reports/q3_board_report.pdf", "read_file", ["q3_board_report.pdf"]),
    (
        "en",
        "I dropped the supplier agreement at /shared/legal/supplier_agreement_hale.docx. What is the notice period?",
        "read_file",
        ["supplier_agreement_hale.docx"],
    ),
    (
        "en",
        "Open /data/support_tickets_october.csv and tell me the most common issue category.",
        "read_file",
        ["support_tickets_october.csv"],
    ),
    # draft_email
    (
        "fr",
        "Prépare un mail à sophie.martin@atelier-lumen.fr pour lui confirmer notre rendez-vous de jeudi à 14 h dans nos locaux.",
        "draft_email",
        ["sophie.martin@atelier-lumen.fr"],
    ),
    (
        "fr",
        "Rédige un courriel pour relancer paul.girard@batipro-ouest.fr au sujet de la facture F-2291, impayée depuis 45 jours. Ton ferme mais courtois.",
        "draft_email",
        ["paul.girard@batipro-ouest.fr", "f-2291"],
    ),
    (
        "fr",
        "Écris un mail à equipe-compta@novalys-industrie.fr pour annoncer que la clôture mensuelle est avancée au 28.",
        "draft_email",
        ["equipe-compta@novalys-industrie.fr"],
    ),
    (
        "fr",
        "Il faut prévenir claire.dubois@cabinet-arvor.fr que je serai absent du 3 au 7 février et que Marc assure l'intérim. Tu me prépares le message ?",
        "draft_email",
        ["claire.dubois@cabinet-arvor.fr", "marc"],
    ),
    (
        "en",
        "Draft an email to james.porter@northgate-freight.co.uk confirming our call on Tuesday at 10 am.",
        "draft_email",
        ["james.porter@northgate-freight.co.uk"],
    ),
    (
        "en",
        "Write an email to accounts@pinecrest-medical.com chasing invoice INV-4471, now 30 days overdue. Polite but firm.",
        "draft_email",
        ["accounts@pinecrest-medical.com", "inv-4471"],
    ),
    (
        "en",
        "I need to let hannah.lee@calder-valley.org know the workshop moves to Room 4. Can you prepare the message?",
        "draft_email",
        ["hannah.lee@calder-valley.org"],
    ),
    # make_slides
    (
        "fr",
        "Fais-moi une présentation de 3 diapositives sur notre nouvelle politique de télétravail : deux jours par semaine, accord du manager requis, matériel fourni par l'entreprise.",
        "make_slides",
        ["manager"],
    ),
    (
        "fr",
        "Prépare un diaporama pour le comité de direction : résultats du T2 (CA 4,2 M€, marge 31 %), les deux priorités du T3 (recrutement, export Espagne) et le risque principal (trésorerie).",
        "make_slides",
        ["espagne"],
    ),
    (
        "fr",
        "J'ai besoin de slides pour présenter l'équipe au nouveau client : Léa (cheffe de projet), Karim (développeur), Inès (design). Une diapo par personne plus une diapo d'introduction.",
        "make_slides",
        ["karim"],
    ),
    (
        "fr",
        "Transforme ces trois points en présentation : 1) le marché croît de 8 % par an ; 2) nous détenons 12 % de parts ; 3) objectif 15 % en 2027.",
        "make_slides",
        ["2027"],
    ),
    (
        "en",
        "Make me a 3-slide deck on our new expense policy: receipts required over £25, approval by line manager, reimbursement within 10 days.",
        "make_slides",
        ["manager"],
    ),
    (
        "en",
        "Turn these points into a presentation for Monday's kickoff: goal (launch by June), team (4 engineers, 1 designer), risks (vendor delay).",
        "make_slides",
        ["june"],
    ),
    # make_document
    (
        "fr",
        "Crée un document intitulé « Fermeture de fin d'année » avec deux sections : les dates (du 24 décembre au 2 janvier) et l'astreinte (Julien, joignable au standard).",
        "make_document",
        ["fermeture", "julien"],
    ),
    (
        "fr",
        "Génère un document « Procédure d'accueil des nouveaux arrivants » avec trois sections : avant l'arrivée, premier jour, premier mois. Quelques lignes par section.",
        "make_document",
        ["accueil"],
    ),
    (
        "fr",
        "Mets ça en forme dans un document de compte rendu : réunion du 14 mai, présents Anne et Hugo ; décision : lancement du pilote en juin ; action : Hugo envoie le planning vendredi.",
        "make_document",
        ["hugo"],
    ),
    (
        "en",
        'Create a document titled "Onboarding checklist" with three sections: before day one, first day, first month. A few lines each.',
        "make_document",
        ["onboarding"],
    ),
    (
        "en",
        "Put this into a meeting-minutes document: 9 April, attendees Priya and Tom; decision: pilot starts in May; action: Tom shares the plan by Friday.",
        "make_document",
        ["priya"],
    ),
    # make_sheet
    (
        "fr",
        "Crée un tableur avec les colonnes Produit, Quantité, Prix unitaire et ces lignes : Stylos, 200, 0,45 ; Cahiers, 150, 1,20 ; Classeurs, 80, 2,10.",
        "make_sheet",
        ["stylos", "classeurs"],
    ),
    (
        "fr",
        "Fais-moi un tableau Excel de suivi des congés : colonnes Nom, Début, Fin, Jours. Lignes : Durand, 03/02, 07/02, 5 ; Petit, 10/02, 12/02, 3.",
        "make_sheet",
        ["durand", "petit"],
    ),
    (
        "fr",
        "J'ai besoin d'une feuille de calcul du budget déplacements : Train 1 240 €, Hôtel 860 €, Repas 415 €, Taxi 130 €. Colonnes Poste et Montant.",
        "make_sheet",
        ["train", "taxi"],
    ),
    (
        "en",
        "Create a spreadsheet with columns Item, Quantity, Unit price and these rows: Pens, 200, 0.45; Notebooks, 150, 1.20; Folders, 80, 2.10.",
        "make_sheet",
        ["pens", "folders"],
    ),
    (
        "en",
        "Build me a sheet for the travel budget: Train 1,240; Hotel 860; Meals 415; Taxi 130. Columns Category and Amount.",
        "make_sheet",
        ["train", "taxi"],
    ),
    # run_python
    (
        "fr",
        "Calcule l'écart-type et la médiane de cette série de délais de livraison (en jours) : 12, 7, 9, 15, 22, 8, 11, 13, 9, 17, 6, 14, 10, 19, 8.",
        "run_python",
        ["22"],
    ),
    (
        "fr",
        "Lance une simulation de 10 000 tirages pour estimer la probabilité que la somme de trois dés dépasse 14.",
        "run_python",
        ["14"],
    ),
    (
        "en",
        "Compute the standard deviation and median of these response times (ms): 212, 187, 340, 295, 178, 402, 266, 231, 319, 204, 288, 351, 199, 273.",
        "run_python",
        ["402"],
    ),
    (
        "en",
        "Run a quick simulation, 10,000 trials, to estimate the probability that at least two people out of 23 share a birthday.",
        "run_python",
        ["23"],
    ),
    # none: mental arithmetic, general knowledge, rewriting, small talk
    ("fr", "Combien font 15 % de 200 ?", "none", []),
    ("fr", "Reformule cette phrase de façon plus professionnelle : « On a pas pu finir à temps, désolé. »", "none", []),
    ("fr", "Quelle est la différence entre un chiffre d'affaires HT et TTC ?", "none", []),
    ("fr", "Traduis en anglais : « Veuillez trouver ci-joint le devis demandé. »", "none", []),
    ("fr", "Bonjour ! Tu peux m'aider aujourd'hui ?", "none", []),
    (
        "fr",
        "Corrige les fautes : « Nous vous remercions pour votre confience et resterons a votre disposition. »",
        "none",
        [],
    ),
    ("fr", "Si un article coûte 80 € HT avec une TVA à 20 %, quel est le prix TTC ?", "none", []),
    ("en", "What's 20% of 150?", "none", []),
    ("en", 'Rewrite this more professionally: "Sorry, we couldn\'t get it done in time."', "none", []),
    ("en", "What's the difference between gross margin and net margin?", "none", []),
    ("en", 'Translate into French: "Please find attached the requested quote."', "none", []),
    ("en", "Thanks, that's all for today!", "none", []),
]

# ---------------------------------------------------------------- lang_follow: (lang, system prompt or None, request)
_EN_SYS = [
    "You are a helpful assistant for the staff of Northgate Freight Ltd. Be concise.",
    "You are an office assistant. Keep answers short and practical.",
    "Internal assistant for a consulting firm. Help employees with writing and organisation.",
    "You are a workplace assistant. Be clear and professional.",
    "You help employees with everyday office tasks.",
]
_FR_PLAIN = [
    "Rédige un court message pour annoncer à l'équipe que la réunion de lundi est reportée à mercredi.",
    "Explique en trois phrases ce qu'est un besoin en fonds de roulement.",
    "Propose-moi un plan en quatre points pour préparer un entretien annuel.",
    "Comment refuser poliment une invitation à un séminaire ? Donne-moi un exemple de réponse.",
    "Résume en deux phrases l'intérêt d'un tableau de bord pour un chef de projet.",
    "Quels sont les avantages du télétravail pour une petite entreprise ?",
    "Écris une courte annonce pour recruter un stagiaire en comptabilité.",
    "Donne-moi trois conseils pour mener une réunion efficace.",
    "Comment présenter un retard de livraison à un client sans le braquer ?",
    "Rédige deux phrases d'accroche pour une offre commerciale destinée aux PME.",
]
_FR_WITH_EN_SYS = [
    "Peux-tu m'expliquer la différence entre un devis et une facture ?",
    "J'ai besoin d'un message d'absence pour ma boîte mail, du 12 au 16 août.",
    "Quelles sont les étapes pour organiser un déplacement professionnel à Lyon ?",
    "Rédige un petit mot de remerciement pour un collègue qui m'a aidé sur un dossier.",
    "Explique simplement ce qu'est une marge brute.",
    "Comment bien structurer un compte rendu de réunion ?",
    "Propose deux formules de politesse pour conclure un courrier à un fournisseur.",
    "Donne-moi deux arguments pour convaincre mon responsable d'acheter un second écran.",
    "Quelles questions poser à un candidat lors d'un entretien d'embauche ?",
    "Écris un rappel courtois pour une note de frais non remise.",
]
_EN_PLAIN = [
    "Write a short message telling the team that Monday's meeting moves to Wednesday.",
    "Explain in three sentences what working capital is.",
    "Give me a four-point plan to prepare for an annual review.",
    "How do I politely decline an invitation to an offsite? Give me an example reply.",
    "In two sentences, why is a dashboard useful to a project manager?",
    "What are the benefits of remote work for a small company?",
    "Write a short ad to recruit an accounting intern.",
    "Give me three tips for running an effective meeting.",
    "How should I tell a client about a late delivery without upsetting them?",
    "Write two opening lines for a sales offer aimed at small businesses.",
    "Can you explain the difference between a quote and an invoice?",
    "I need an out-of-office message for 12 to 16 August.",
    "What are the steps to organise a business trip to Manchester?",
    "Write a short thank-you note for a colleague who helped me on a case.",
    "Explain gross margin in simple terms.",
    "How should I structure meeting minutes?",
    "Suggest two sign-offs to close a letter to a supplier.",
    "Give me two arguments to convince my manager to buy a second monitor.",
    "Which questions should I ask a candidate in a job interview?",
    "Write a polite reminder about an expense report that has not been handed in.",
]
LANG_FOLLOW = (
    [("fr", None, q) for q in _FR_PLAIN]
    + [("fr", _EN_SYS[i % len(_EN_SYS)], q) for i, q in enumerate(_FR_WITH_EN_SYS)]
    + [("en", None, q) for q in _EN_PLAIN]
)

# ---------------------------------------------------------------- concision: (lang, question, accepted gold spans)
_CTRL_C = ["ctrl+c", "ctrl + c", "ctrl c", "control + c", "control+c", "contrôle + c", "contrôle+c"]
CONCISION = [
    ("fr", "Quelle est la capitale de l'Australie ?", ["Canberra"]),
    ("fr", "Combien de jours compte une année bissextile ?", ["366"]),
    ("fr", "Que signifie le sigle TVA ?", ["taxe sur la valeur ajoutée"]),
    ("fr", "Quel est le taux normal de TVA en France ?", ["20"]),
    ("fr", "Combien y a-t-il de minutes dans une journée de 24 heures ?", ["1440"]),
    ("fr", "Quelle est la monnaie du Japon ?", ["yen"]),
    (
        "fr",
        "Que signifie PME ?",
        [
            "petites et moyennes entreprises",
            "petite et moyenne entreprise",
            "petite ou moyenne entreprise",
            "petites ou moyennes entreprises",
        ],
    ),
    ("fr", "Combien font 12 fois 12 ?", ["144"]),
    ("fr", "Dans quelle ville se trouve le siège de la Banque centrale européenne ?", ["Francfort"]),
    ("fr", "Quel raccourci clavier permet de copier un texte sous Windows ?", _CTRL_C),
    ("fr", "Combien de trimestres y a-t-il dans une année ?", ["4", "quatre"]),
    ("fr", "Quelle est la capitale du Canada ?", ["Ottawa"]),
    ("fr", "Que signifie l'abréviation RH en entreprise ?", ["ressources humaines"]),
    ("fr", "Combien de centimètres y a-t-il dans un mètre ?", ["100", "cent"]),
    ("fr", "En quelle année les pièces et billets en euros sont-ils entrés en circulation ?", ["2002"]),
    ("en", "What is the capital of Australia?", ["Canberra"]),
    ("en", "How many days are there in a leap year?", ["366"]),
    ("en", "What does VAT stand for?", ["value added tax"]),
    ("en", "How many minutes are there in a 24-hour day?", ["1440"]),
    ("en", "What is the currency of Japan?", ["yen"]),
    ("en", "What does CEO stand for?", ["chief executive officer"]),
    ("en", "What is 12 times 12?", ["144"]),
    ("en", "In which city is the European Central Bank headquartered?", ["Frankfurt"]),
    ("en", "Which keyboard shortcut copies text on Windows?", _CTRL_C),
    ("en", "How many quarters are there in a year?", ["4", "four"]),
    ("en", "What is the capital of Canada?", ["Ottawa"]),
    ("en", "What does HR stand for in a company?", ["human resources"]),
    ("en", "How many centimetres are there in a metre?", ["100", "hundred"]),
    ("en", "What does KPI stand for?", ["key performance indicator"]),
    ("en", "What is the chemical symbol for gold?", ["Au"]),
]
