"""Maps trigger bench data (scripts/trigger_bench.py, families « maps_real » and « maps_office »).

200 realistic phrasings of a map ask (typos, no accents, lowercase, voice dictation, English, pasted addresses and
lists, distances, « adresse de », « plan d'accès », « comment venir », « le plus proche », « autour de moi », « sur
une carte ») and 60 ordinary office prompts that must never reach the geocoder. Each map ask carries what the
harness must do with it:

- ("where", query) / ("address", query): one place looked up whole;
- ("near", kind, near): a kind of place around a place;
- ("route", a, b): two places and the distance between them (either order);
- ("list", [items]): several places on one map, in the order given;
- ("ask", None): « autour de moi »: the position is unknown, Bird asks for a place (nothing geocoded);
- ("offer", None): a map ask whose place is elsewhere (the tool is offered, nothing is pre-called).
"""

from __future__ import annotations

W, A, N, R, L, ASK, OFFER = "where", "address", "near", "route", "list", "ask", "offer"

MAPS_REAL: list[tuple[str, tuple]] = [
    # ---- typos, no accents, lowercase, phone typing (40)
    ("ou est la tour eiffel", (W, "tour eiffel")),
    ("ou se trouve la gare montparnasse", (W, "gare montparnasse")),
    ("c ou le musee du louvre", (W, "musee du louvre")),
    ("cest ou la gare saint lazare", (W, "gare saint lazare")),
    ("ou ce trouve la mairie de nantes", (W, "mairie de nantes")),
    ("ou es la cathedrale de reims", (W, "cathedrale de reims")),
    ("ou sa se trouve le stade velodrome", (W, "stade velodrome")),
    ("ou ce situe l'aeroport de beauvais", (W, "aeroport de beauvais")),
    ("adresse de la prefecture de lyon", (W, "prefecture de lyon")),
    ("adrese de la mairie de lille", (W, "mairie de lille")),
    ("l'adresse du musee d'orsay stp", (W, "musee d'orsay")),
    ("pharmacie pres de la gare de rennes", (N, "pharmacy", "gare de rennes")),
    ("pharamcie a cote de la place bellecour", (N, "pharmacy", "place bellecour")),
    ("resto pas loin de la gare du nord", (N, "restaurant", "gare du nord")),
    ("restos vers le vieux port", (N, "restaurant", "vieux port")),
    ("hotel proche gare part dieu", (N, "hotel", "gare part dieu")),
    ("un hotel pas trop loin de l'aeroport de nice", (N, "hotel", "aeroport de nice")),
    ("parking proche de la gare de bordeaux", (N, "parking", "gare de bordeaux")),
    ("y a un parking vers la place du capitole", (N, "parking", "place du capitole")),
    ("boulangerie autour de la place de la republique", (N, "bakery", "place de la republique")),
    ("cafe pres du jardin du luxembourg", (N, "cafe", "jardin du luxembourg")),
    ("supermarche a cote de la gare de l'est", (N, "supermarket", "gare de l'est")),
    ("distributeur pres de l'opera garnier", (N, "atm", "opera garnier")),
    ("borne de recharge pres de l'aeroport de lyon", (N, "charging station", "aeroport de lyon")),
    ("coworking a nantes", (N, "coworking", "nantes")),
    ("une pharmacie a strasbourg", (N, "pharmacy", "strasbourg")),
    ("hotels a annecy", (N, "hotel", "annecy")),
    ("garage auto a chartres", (N, "car_repair", "chartres")),
    ("les hotels de biarritz", (N, "hotel", "biarritz")),
    ("ou est grenoble", (W, "grenoble")),
    ("c'est ou brive", (W, "brive")),
    ("ou se trouve saint-malo", (W, "saint-malo")),
    ("c koi l'adresse de la tour montparnasse", (W, "tour montparnasse")),
    ("itineraire gare de lyon tour eiffel", (R, "gare de lyon", "tour eiffel")),
    ("trajet lille bruxelles", (R, "lille", "bruxelles")),
    ("itineraire lyon -> grenoble", (R, "lyon", "grenoble")),
    ("comment aller a la gare de lyon depuis montparnasse", (R, "gare de lyon", "montparnasse")),
    ("comment aller au stade de france", (R, None, "stade de france")),
    ("ou se trouve le 15 rue de la paix paris", (A, "15 rue de la paix paris")),
    ("ou est le 3 avenue foch 75116 paris", (A, "3 avenue foch 75116 paris")),
    # ---- voice dictation (15)
    ("euh trouve moi une pharmacie à côté de la gare de Rennes", (N, "pharmacy", "gare de Rennes")),
    ("est-ce que tu peux me dire c'est où la mairie de Nantes", (W, "mairie de Nantes")),
    ("dis-moi où se trouve le musée des Confluences s'il te plaît", (W, "musée des Confluences")),
    (
        "alors je cherche un hôtel près de la gare Saint-Charles à Marseille",
        (N, "hotel", "gare Saint-Charles à Marseille"),
    ),
    ("bonjour je voudrais savoir où se trouve la cité des sciences", (W, "cité des sciences")),
    ("ok donc il me faudrait un parking près de la gare de Lille Flandres", (N, "parking", "gare de Lille Flandres")),
    ("tu peux me trouver un restaurant près de la place Stanislas", (N, "restaurant", "place Stanislas")),
    ("je veux savoir où est le palais des papes", (W, "palais des papes")),
    ("bon montre-moi où est la gare de Nantes", (W, "gare de Nantes")),
    ("trouve-moi un café pas loin du Panthéon", (N, "cafe", "Panthéon")),
    (
        "est-ce qu'il y a une boulangerie près de la place du Marché à Versailles",
        (N, "bakery", "place du Marché à Versailles"),
    ),
    ("c'est quoi l'adresse de l'hôtel de ville de Bordeaux", (W, "hôtel de ville de Bordeaux")),
    ("il me faudrait l'itinéraire de la gare de Lyon jusqu'à la tour Eiffel", (R, "gare de Lyon", "tour Eiffel")),
    ("dis-moi la distance entre Lyon et Grenoble", (R, "Lyon", "Grenoble")),
    ("tu sais où est le château de Versailles", (W, "château de Versailles")),
    # ---- English (20)
    ("where is the Eiffel Tower", (W, "Eiffel Tower")),
    ("where's the Louvre museum", (W, "Louvre museum")),
    ("what's the address of the Lyon town hall", (W, "Lyon town hall")),
    ("restaurants near Gare du Nord", (N, "restaurant", "Gare du Nord")),
    ("a pharmacy near the Opera in Paris", (N, "pharmacy", "Opera in Paris")),
    ("hotels close to Nice airport", (N, "hotel", "Nice airport")),
    ("nearest parking to the Stade de France", (N, "parking", "Stade de France")),
    ("the closest ATM to Place Bellecour", (N, "atm", "Place Bellecour")),
    ("coffee shops around Notre-Dame", (N, "cafe", "Notre-Dame")),
    ("how far is Lyon from Paris", (R, "Lyon", "Paris")),
    ("distance between Marseille and Nice", (R, "Marseille", "Nice")),
    ("how many km from Lille to Brussels", (R, "Lille", "Brussels")),
    ("directions from Gare de Lyon to the Louvre", (R, "Gare de Lyon", "Louvre")),
    ("how do I get to Orly airport", (R, None, "Orly airport")),
    ("show me Bordeaux on a map", (W, "Bordeaux")),
    ("put these on a map: Lyon, Marseille, Lille", (L, ["Lyon", "Marseille", "Lille"])),
    (
        "map these addresses: 10 rue de Rivoli Paris; 5 place Bellecour Lyon",
        (L, ["10 rue de Rivoli Paris", "5 place Bellecour Lyon"]),
    ),
    ("where is Toulouse", (W, "Toulouse")),
    ("locate the Palais des Congrès in Paris", (W, "Palais des Congrès in Paris")),
    ("hotels near me", (ASK, None)),
    # ---- addresses pasted alone (15)
    ("10 rue de Rivoli, 75001 Paris", (A, "10 rue de Rivoli, 75001 Paris")),
    ("5 place Bellecour 69002 Lyon", (A, "5 place Bellecour 69002 Lyon")),
    ("1 La Canebière 13001 Marseille", (A, "1 La Canebière 13001 Marseille")),
    ("20 avenue de Ségur, 75007 Paris ?", (A, "20 avenue de Ségur, 75007 Paris")),
    ("12 bis rue des Lilas 35000 Rennes", (A, "12 bis rue des Lilas 35000 Rennes")),
    ("3 quai des Chartrons, Bordeaux", (A, "3 quai des Chartrons, Bordeaux")),
    ("8 boulevard Haussmann Paris", (A, "8 boulevard Haussmann Paris")),
    ("2 place de la Comédie 34000 Montpellier", (A, "2 place de la Comédie 34000 Montpellier")),
    ("45 cours Mirabeau Aix-en-Provence", (A, "45 cours Mirabeau Aix-en-Provence")),
    ("14 rue Sainte-Catherine 33000 Bordeaux", (A, "14 rue Sainte-Catherine 33000 Bordeaux")),
    ("7 allée des Tilleuls 44000 Nantes", (A, "7 allée des Tilleuls 44000 Nantes")),
    ("100 avenue des Champs-Élysées", (A, "100 avenue des Champs-Élysées")),
    ("c'est où 6 rue de la République Lyon ?", (A, "6 rue de la République Lyon")),
    ("situe 25 rue du Faubourg Saint-Honoré Paris", (A, "25 rue du Faubourg Saint-Honoré Paris")),
    ("1 place du Capitole, Toulouse", (A, "1 place du Capitole, Toulouse")),
    # ---- distances: « c'est loin », « combien de km », « distance entre » (20)
    ("c'est loin Lyon de Paris ?", (R, "Lyon", "Paris")),
    ("c'est loin la gare de Lyon de la tour Eiffel ?", (R, "gare de Lyon", "tour Eiffel")),
    ("c'est loin Versailles de Paris", (R, "Versailles", "Paris")),
    ("combien de km entre Lyon et Marseille ?", (R, "Lyon", "Marseille")),
    ("combien de kilomètres entre Nantes et Rennes", (R, "Nantes", "Rennes")),
    ("combien de km de Paris à Lille", (R, "Paris", "Lille")),
    ("combien de km entre la gare du Nord et la gare de l'Est", (R, "gare du Nord", "gare de l'Est")),
    ("distance entre Bordeaux et Toulouse", (R, "Bordeaux", "Toulouse")),
    ("quelle distance entre Lille et Bruxelles ?", (R, "Lille", "Bruxelles")),
    ("quelle est la distance entre la tour Eiffel et le Louvre ?", (R, "tour Eiffel", "Louvre")),
    ("distance paris marseille", (R, "paris", "marseille")),
    ("distance lyon grenoble", (R, "lyon", "grenoble")),
    ("y a combien de km entre strasbourg et colmar", (R, "strasbourg", "colmar")),
    ("Lyon Marseille c'est combien de km ?", (R, "Lyon", "Marseille")),
    ("c'est à combien de km Orléans de Paris ?", (R, "Orléans", "Paris")),
    ("à quelle distance est Versailles de Paris ?", (R, "Versailles", "Paris")),
    ("quel est le temps de trajet entre Lyon et Paris ?", (R, "Lyon", "Paris")),
    ("Nice est à combien de Cannes ?", (R, "Nice", "Cannes")),
    ("combien de temps pour aller de Lille à Paris", (R, "Lille", "Paris")),
    ("c'est loin d'ici la gare ?", (OFFER, None)),
    # ---- « adresse de », « plan d'accès », « comment venir » (20)
    ("adresse de la mairie de Toulouse", (W, "mairie de Toulouse")),
    ("donne-moi l'adresse du siège de la SNCF", (W, "siège de la SNCF")),
    ("quelle est l'adresse de la gare de Lille Europe ?", (W, "gare de Lille Europe")),
    ("l'adresse exacte du Stade de France", (W, "Stade de France")),
    ("adresse du palais des congrès de Lyon", (W, "palais des congrès de Lyon")),
    ("plan d'accès du parc des expositions de Villepinte", (W, "parc des expositions de Villepinte")),
    ("plan d'accès au palais des congrès de Paris", (W, "palais des congrès de Paris")),
    ("un plan d'accès pour la gare de Versailles-Chantiers", (W, "gare de Versailles-Chantiers")),
    ("plan d'accès à l'aéroport d'Orly", (W, "aéroport d'Orly")),
    ("plan de situation de la mairie de Nantes", (W, "mairie de Nantes")),
    ("comment venir au palais des congrès de Paris ?", (R, None, "palais des congrès de Paris")),
    ("comment venir à la gare de Lyon", (R, None, "gare de Lyon")),
    ("comment se rendre au Stade de France", (R, None, "Stade de France")),
    (
        "comment venir au parc des expositions de Bordeaux depuis la gare Saint-Jean",
        (R, "gare Saint-Jean", "parc des expositions de Bordeaux"),
    ),
    ("comment je fais pour aller à la tour Eiffel", (R, None, "tour Eiffel")),
    ("comment on va au château de Versailles", (R, None, "château de Versailles")),
    ("accès au centre des congrès de Lyon", (W, "centre des congrès de Lyon")),
    ("comment venir chez vous", (OFFER, None)),
    ("envoie-moi le plan d'accès du salon", (OFFER, None)),
    ("adresse de l'hôtel Negresco à Nice", (W, "hôtel Negresco à Nice")),
    # ---- « le plus proche » (12)
    ("la pharmacie la plus proche de la gare Saint-Charles", (N, "pharmacy", "gare Saint-Charles")),
    ("le parking le plus proche du stade de France", (N, "parking", "stade de France")),
    ("quel est le distributeur le plus proche de l'Opéra ?", (N, "atm", "Opéra")),
    ("l'hôtel le plus proche de l'aéroport de Nantes", (N, "hotel", "aéroport de Nantes")),
    ("la station de métro la plus proche de la tour Eiffel", (N, "subway station", "tour Eiffel")),
    ("la boulangerie la plus proche de la place Bellecour", (N, "bakery", "place Bellecour")),
    ("quelle est la gare la plus proche de Toussus-le-Noble ?", (N, "train station", "Toussus-le-Noble")),
    ("le café le plus proche du Louvre", (N, "cafe", "Louvre")),
    ("l'hôpital le plus proche de Chamonix", (N, "hospital", "Chamonix")),
    ("la pharmacie la plus proche", (ASK, None)),
    ("le parking le plus proche", (ASK, None)),
    ("la boulangerie la plus proche d'ici", (ASK, None)),
    # ---- « autour de moi » / « près de moi » (10)
    ("restaurants autour de moi", (ASK, None)),
    ("une pharmacie près de moi", (ASK, None)),
    ("un parking à proximité de moi", (ASK, None)),
    ("y a quoi comme cafés autour de moi ?", (ASK, None)),
    ("pharmacie ouverte près de chez moi", (ASK, None)),
    ("trouve un hôtel près d'ici", (ASK, None)),
    ("coffee shops near me", (ASK, None)),
    ("les restos du coin", (ASK, None)),
    ("une boulangerie dans le coin", (ASK, None)),
    ("où est la pharmacie la plus proche de moi ?", (ASK, None)),
    # ---- « sur une carte » (16)
    (
        "montre sur une carte : 10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille",
        (L, ["10 rue de Rivoli Paris", "5 place Bellecour Lyon", "1 La Canebière Marseille"]),
    ),
    ("montre-moi Lyon sur une carte", (W, "Lyon")),
    ("mets Bordeaux sur la carte", (W, "Bordeaux")),
    ("affiche la tour Eiffel sur une carte", (W, "tour Eiffel")),
    ("situe Brest sur une carte", (W, "Brest")),
    ("sur une carte, la gare de Lyon", (W, "gare de Lyon")),
    ("peux-tu placer ces villes sur une carte : Rennes, Brest, Quimper", (L, ["Rennes", "Brest", "Quimper"])),
    ("mets sur une carte Lyon, Marseille et Lille", (L, ["Lyon", "Marseille", "Lille"])),
    ("une carte avec Lyon, Grenoble et Annecy", (L, ["Lyon", "Grenoble", "Annecy"])),
    ("carte de la Corse", (W, "Corse")),
    ("la carte du quartier de la Défense", (W, "quartier de la Défense")),
    ("montre-moi sur une carte les agences de Lyon, Marseille et Lille", (L, ["Lyon", "Marseille", "Lille"])),
    ("nos agences de Lyon, Marseille et Lille sur une carte", (L, ["Lyon", "Marseille", "Lille"])),
    ("affiche nos bureaux de Paris et Lyon sur une carte", (L, ["Paris", "Lyon"])),
    ("mets ça sur une carte", (OFFER, None)),
    ("place Nantes et Angers sur la carte", (L, ["Nantes", "Angers"])),
    # ---- multi-address / multi-place lists (25)
    (
        "affiche ces adresses sur une carte :\n- 10 rue de Rivoli, Paris\n- 5 place Bellecour, Lyon\n- 1 La Canebière, Marseille",
        (L, ["10 rue de Rivoli, Paris", "5 place Bellecour, Lyon", "1 La Canebière, Marseille"]),
    ),
    (
        "carte de nos agences :\n12 rue de la République Lyon\n3 quai des Chartrons Bordeaux\n8 rue Nationale Lille",
        (L, ["12 rue de la République Lyon", "3 quai des Chartrons Bordeaux", "8 rue Nationale Lille"]),
    ),
    ("place ces sites : Lyon Part-Dieu ; Lille Europe ; Nantes", (L, ["Lyon Part-Dieu", "Lille Europe", "Nantes"])),
    ("localise ces magasins : Rennes, Brest et Quimper", (L, ["Rennes", "Brest", "Quimper"])),
    (
        "compare ces sites : gare de Lyon, gare du Nord, gare Montparnasse",
        (L, ["gare de Lyon", "gare du Nord", "gare Montparnasse"]),
    ),
    (
        "mets sur une carte :\n• Tour Eiffel\n• Louvre\n• Arc de Triomphe",
        (L, ["Tour Eiffel", "Louvre", "Arc de Triomphe"]),
    ),
    (
        "voici nos 4 entrepôts, montre-les sur une carte :\n1. Lyon\n2. Marseille\n3. Lille\n4. Toulouse",
        (L, ["Lyon", "Marseille", "Lille", "Toulouse"]),
    ),
    (
        "adresse\n10 rue de Rivoli 75001 Paris\n5 place Bellecour 69002 Lyon\n2 place de la Comédie 34000 Montpellier",
        (
            L,
            ["10 rue de Rivoli 75001 Paris", "5 place Bellecour 69002 Lyon", "2 place de la Comédie 34000 Montpellier"],
        ),
    ),
    (
        "nom;adresse\nAgence Lyon;12 rue de la République 69002 Lyon\nAgence Lille;8 rue Nationale 59000 Lille",
        (L, ["12 rue de la République 69002 Lyon", "8 rue Nationale 59000 Lille"]),
    ),
    ("dans quel ordre visiter : Lyon, Grenoble, Annecy, Chambéry ?", (L, ["Lyon", "Grenoble", "Annecy", "Chambéry"])),
    (
        "optimise ma tournée : Rennes ; Vannes ; Lorient ; Quimper ; Brest",
        (L, ["Rennes", "Vannes", "Lorient", "Quimper", "Brest"]),
    ),
    (
        "dans quel ordre visiter ces clients :\n10 rue de Rivoli Paris\n20 avenue de Ségur Paris\n8 boulevard Haussmann Paris",
        (L, ["10 rue de Rivoli Paris", "20 avenue de Ségur Paris", "8 boulevard Haussmann Paris"]),
    ),
    ("distances entre Paris, Lyon et Marseille", (L, ["Paris", "Lyon", "Marseille"])),
    (
        "situe nos implantations : Paris, Lyon, Bordeaux, Nantes, Lille, Strasbourg",
        (L, ["Paris", "Lyon", "Bordeaux", "Nantes", "Lille", "Strasbourg"]),
    ),
    ("montre sur une carte la tour Eiffel et le Louvre", (L, ["tour Eiffel", "Louvre"])),
    (
        "carte : Lyon ; Marseille ; Nice ; Toulouse ; Bordeaux ; Nantes ; Rennes ; Lille ; Strasbourg ; Dijon",
        (L, ["Lyon", "Marseille", "Nice", "Toulouse", "Bordeaux", "Nantes", "Rennes", "Lille", "Strasbourg", "Dijon"]),
    ),
    ("map: Paris, London, Brussels", (L, ["Paris", "London", "Brussels"])),
    (
        "show these on a map:\n- Eiffel Tower\n- Louvre Museum\n- Notre-Dame",
        (L, ["Eiffel Tower", "Louvre Museum", "Notre-Dame"]),
    ),
    ("où sont ces villes : Rodez, Albi, Millau ?", (L, ["Rodez", "Albi", "Millau"])),
    (
        "situe sur une carte la gare de Lyon et 20 avenue de Ségur Paris",
        (L, ["gare de Lyon", "20 avenue de Ségur Paris"]),
    ),
    (
        "affiche nos magasins sur une carte : Lyon Part-Dieu, Lille Europe, Nantes",
        (L, ["Lyon Part-Dieu", "Lille Europe", "Nantes"]),
    ),
    (
        "10 rue de Rivoli Paris\n5 place Bellecour Lyon\n1 La Canebière Marseille",
        (L, ["10 rue de Rivoli Paris", "5 place Bellecour Lyon", "1 La Canebière Marseille"]),
    ),
    ("10 rue de Rivoli Paris ; 5 place Bellecour Lyon", (L, ["10 rue de Rivoli Paris", "5 place Bellecour Lyon"])),
    ("ou sont lyon marseille et lille sur une carte", (L, ["lyon", "marseille", "lille"])),
    ("itinéraire Paris, Lyon, Marseille", (L, ["Paris", "Lyon", "Marseille"])),
    # ---- kinds near places, spoken variety (7)
    ("des restos sympas vers la place du Capitole ?", (N, "restaurant", "place du Capitole")),
    ("un bar pas loin de la gare du Nord", (N, "bar", "gare du Nord")),
    ("quels hôtels autour du Mont-Saint-Michel ?", (N, "hotel", "Mont-Saint-Michel")),
    ("y a-t-il une pharmacie de garde à Lyon ?", (N, "pharmacy", "Lyon")),
    ("trouve des salles de réunion près de la gare Part-Dieu", (N, "conference centre", "gare Part-Dieu")),
    ("je cherche une imprimerie vers la Bastille", (N, "copyshop", "Bastille")),
    ("restaurants ouverts le dimanche près de la gare de Lyon", (N, "restaurant", "gare de Lyon")),
]

# 60 ordinary office prompts: none may start or even offer a map
MAPS_OFFICE_NO: list[str] = [
    "fais-moi une carte de visite pour Paul",
    "un plan d'action pour le trimestre",
    "quelle est l'adresse mail du support ?",
    "où en est le projet Atlas ?",
    "où en est-on sur le recrutement ?",
    "rédige le plan de la présentation de lundi",
    "fais un plan pour mon rapport",
    "adresse-moi le compte rendu",
    "comment adresser ce problème au client ?",
    "la carte des vins du séminaire",
    "situe le contexte avant d'expliquer",
    "c'est loin d'être fini, ce dossier",
    "la deadline est-elle encore loin ?",
    "qui est le plus proche collaborateur du directeur ?",
    "quelle est la valeur la plus proche de 100 dans ce tableau ?",
    "trouve la date la plus proche pour la réunion",
    "comment venir à bout de ce dossier ?",
    "comment venir en aide à un collègue en difficulté ?",
    "la distance entre nos positions dans la négociation",
    "quelle distance garder avec un client exigeant ?",
    "combien de km de câble faut-il pour l'open space ?",
    "calcule les frais kilométriques : 320 km à 0,6 €",
    "autour de moi tout le monde est en télétravail",
    "les gens autour de moi n'aiment pas le changement",
    "localise la chaîne de caractères dans ce fichier",
    "où est le fichier du budget ?",
    "c'est où qu'on configure l'imprimante ?",
    "où se trouve le menu Insertion dans Word ?",
    "mets ça dans un tableau",
    "place ce paragraphe en introduction",
    "affiche les chiffres sur un graphique",
    "itinéraire de carrière d'un chef de projet",
    "le trajet professionnel d'un consultant",
    "quel est le meilleur parcours de formation ?",
    "plan d'accès au VPN de l'entreprise",
    "fais une carte mentale du projet",
    "ma carte bancaire est bloquée",
    "carte grise de la voiture de service",
    "commande des cartes de visite",
    "prépare un plan de communication",
    "une adresse IP fixe pour le serveur",
    "envoie à cette adresse : paul@example.com",
    "quelle est l'adresse du site web du client ?",
    "où est passé le rapport Q3 ?",
    "où en sont les ventes de novembre ?",
    "rédige un mail à Paul pour la réunion de Lyon",
    "réserve une salle pour la réunion de jeudi",
    "fais un résumé du document",
    "traduis ce texte en anglais",
    "les points clés de la réunion d'hier",
    "liste les tâches de la semaine",
    "combien de temps pour finir le dossier ?",
    "c'est à combien le taux de TVA ?",
    "quel est le chemin du dossier partagé ?",
    "suis-je proche de l'objectif de ventes ?",
    "le client le plus proche de la signature",
    "un plan de table pour le dîner d'équipe",
    "corrige les fautes : on se retrouve à Lyon demain",
    "écris une fonction qui calcule la distance entre deux points",
    "qui habite près de chez Julie ?",
]


# written after the parsers were changed for MAPS_REAL (before their own fixes: 26/30 right, 5/15 false)
MAPS_HELDOUT: list[tuple[str, tuple]] = [
    ("ou se trouve le palais de justice de rennes", (W, "palais de justice de rennes")),
    ("c'est où la gare de Marseille Saint-Charles ?", (W, "gare de Marseille Saint-Charles")),
    ("adresse du musée Grévin", (W, "musée Grévin")),
    ("une boulangerie près de la gare de Tours", (N, "bakery", "gare de Tours")),
    ("hotel pas loin du parc des expos de lyon", (N, "hotel", "parc des expos de lyon")),
    ("des parkings autour de la place de la Bourse à Bordeaux", (N, "parking", "place de la Bourse à Bordeaux")),
    ("la pharmacie la plus proche de la mairie de Lille", (N, "pharmacy", "mairie de Lille")),
    ("le resto le plus proche de la gare de Nice", (N, "restaurant", "gare de Nice")),
    ("combien de km entre Brest et Rennes ?", (R, "Brest", "Rennes")),
    ("c'est loin Annecy de Genève ?", (R, "Annecy", "Genève")),
    ("distance entre la gare de Lyon et Bercy", (R, "gare de Lyon", "Bercy")),
    ("how far is Bordeaux from Toulouse?", (R, "Bordeaux", "Toulouse")),
    ("comment venir au musée du Louvre depuis la gare du Nord", (R, "gare du Nord", "musée du Louvre")),
    ("comment aller à l'aéroport de Lyon", (R, None, "aéroport de Lyon")),
    ("plan d'accès du stade Pierre-Mauroy", (W, "stade Pierre-Mauroy")),
    ("18 rue du Vieux-Marché-aux-Poissons Strasbourg", (A, "18 rue du Vieux-Marché-aux-Poissons Strasbourg")),
    ("4 place Kléber 67000 Strasbourg", (A, "4 place Kléber 67000 Strasbourg")),
    ("montre sur une carte : Toulouse ; Albi ; Castres", (L, ["Toulouse", "Albi", "Castres"])),
    ("situe nos agences : Rouen, Caen et Le Havre", (L, ["Rouen", "Caen", "Le Havre"])),
    (
        "mets sur une carte :\n- 4 place Kléber Strasbourg\n- 1 place du Capitole Toulouse",
        (L, ["4 place Kléber Strasbourg", "1 place du Capitole Toulouse"]),
    ),
    ("dans quel ordre visiter Nantes, Angers, Le Mans et Tours ?", (L, ["Nantes", "Angers", "Le Mans", "Tours"])),
    (
        "ville;adresse\nLyon;5 place Bellecour 69002 Lyon\nParis;10 rue de Rivoli 75001 Paris",
        (L, ["5 place Bellecour 69002 Lyon", "10 rue de Rivoli 75001 Paris"]),
    ),
    ("une pharmacie autour de moi stp", (ASK, None)),
    ("the nearest pharmacy", (ASK, None)),
    ("where is the Colosseum", (W, "Colosseum")),
    ("restaurants near the Louvre", (N, "restaurant", "Louvre")),
    ("show Lyon, Grenoble and Annecy on a map", (L, ["Lyon", "Grenoble", "Annecy"])),
    ("ou est le pont du gard", (W, "pont du gard")),
    ("cherche un coworking pres de la gare de lille europe", (N, "coworking", "gare de lille europe")),
    ("distance lille paris", (R, "lille", "paris")),
    # the lead-in and the question are never glued onto the first place (review of the maps branch)
    (
        "Je dois passer chez trois clients demain : 12 rue de la République Lyon, 3 cours Lafayette Lyon, "
        "8 quai Saint-Antoine Lyon. Dans quel ordre ?",
        (L, ["12 rue de la République Lyon", "3 cours Lafayette Lyon", "8 quai Saint-Antoine Lyon"]),
    ),
    ("Quel ordre pour visiter mes clients à Lyon, Villeurbanne et Bron ?", (L, ["Lyon", "Villeurbanne", "Bron"])),
    (
        "Quel est le plus court chemin pour visiter Rennes, Brest, Quimper, Vannes ?",
        (L, ["Rennes", "Brest", "Quimper", "Vannes"]),
    ),
]
MAPS_HELDOUT_NO: list[str] = [
    "fais une carte des risques du projet",
    "la distance entre le prévu et le réalisé",
    "comment venir à bout des retards ?",
    "plan d'accès aux données du CRM",
    "localise l'erreur dans le script",
    "situe ce chiffre par rapport à l'an dernier",
    "mets ces chiffres sur un graphique : 10, 20, 30",
    "où en est la commande du client Lyon ?",
    "le collaborateur le plus proche de la retraite",
    "affiche les ventes de Lyon, Marseille et Lille",
    "compare les ventes de Paris et Lyon",
    "envoie le devis à l'agence de Lyon",
    "liste les clients de Lyon, Marseille et Lille",
    "écris un mail aux agences de Lyon et Marseille",
    "quelle est l'adresse de facturation ?",
    # general knowledge with « distance entre » (review of the maps branch: map cards before the fix)
    "Quelle est la distance entre la Terre et le Soleil ?",
    "Quelle distance entre Mars et Jupiter ?",
    "Quelle est la distance en km entre la Terre et la Lune ?",
    "how far is the Earth from the Moon?",
    "distance between Mars and Jupiter",
    # an address written into a document is an edit, not a map ask
    "Ajoute 12 rue de la Paix à mon CV.",
    "Mets à jour ma signature : 5 rue de la République 69002 Lyon",
    "Corrige l'adresse 10 rue de Rivoli Paris dans le courrier",
    "add 10 Downing Street London to my resume",
]


def _f(s) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^\w']+", " ", t).split())


def _intent(text: str):
    from birds.harness import intents

    return next((i for i in intents.detect(text, False, "fr") if i.tool == "find_places"), None)


def detected(text: str) -> bool:
    """Bird reacts to the ask at all (a pre-call, an offered tool or an « autour de quel lieu ? » question)."""
    return _intent(text) is not None


def correct(item) -> bool:
    """Bird does the right thing with the right arguments."""
    text, spec = item
    got = _intent(text)
    if got is None:
        return False
    kind, a = spec[0], spec[1:]
    args = got.args or {}
    if kind == ASK:
        return got.mode == "ask" and not got.args
    if kind == OFFER:
        return not got.args and got.mode != "ask"
    if not got.args:
        return False
    if kind in (W, A):
        return got.mode in ("where", "address") and _f(args.get("query")) == _f(a[0])
    if kind == N:
        return got.mode == "near" and args.get("query") == a[0] and _f(args.get("near")) == _f(a[1])
    if kind == R:
        pair = {_f(args.get("query")), _f(args.get("near"))}
        want = {_f(x) for x in a if x is not None} | ({""} if a[0] is None else set())
        return got.mode == "route" and pair == want
    if kind == L:
        items = [x.strip() for x in str(args.get("query") or "").split(";")]
        return got.mode == "list" and [_f(x) for x in items] == [_f(x) for x in a[0]]
    return False


def office_clean(text: str) -> bool:
    """An office prompt: no place intent at all (not even offered)."""
    return _intent(text) is None


# ---- category near a town (production report of 28/11/2026, « supermarchés à Saint-Cloud »): the user's ask, the
# category and anchor the parsers must read, and the query the model wrote for it (« supermarché »); the code must
# map that query to the OSM category, never look the word up as a name across the world
MAPS_CATEGORY: list[tuple[str, str, str, str]] = [
    ("quels sont les supermarchés à Saint-Cloud", "supermarket", "saint-cloud", "supermarché"),
    ("supermarchés à Montreuil", "supermarket", "montreuil", "supermarchés"),
    ("un supermarché à Annecy", "supermarket", "annecy", "les supermarchés"),
    ("pharmacie de garde à Lyon 3e", "pharmacy", "lyon 3e", "pharmacie de garde"),
    ("une pharmacie à Nantes", "pharmacy", "nantes", "pharmacies"),
    ("boulangerie près de la gare de Rennes", "bakery", "gare de rennes", "boulangerie"),
    ("boulangeries à Quimper", "bakery", "quimper", "boulangeries"),
    ("parking près de l'hôpital de Nantes", "parking", "hôpital de nantes", "parking"),
    ("restaurants végétariens à Bordeaux", "restaurant", "bordeaux", "restaurants végétariens"),
    ("un restaurant à Colmar", "restaurant", "colmar", "restaurant"),
    ("distributeur près de la Défense", "atm", "défense", "distributeur"),
    ("un dab à Brest", "atm", "brest", "dab"),
    ("station-service à Annecy", "fuel", "annecy", "station-service"),
    ("hôpital à Versailles", "hospital", "versailles", "hôpital"),
    ("une gare près de Chantilly", "train station", "chantilly", "gare"),
    ("banque à Saint-Malo", "bank", "saint-malo", "banque"),
    ("bureau de poste à Vannes", "post office", "vannes", "bureau de poste"),
    ("écoles à Versailles", "school", "versailles", "écoles"),
    ("supermarkets in Lyon", "supermarket", "lyon", "supermarkets"),
    ("pharmacy near Montparnasse station", "pharmacy", "montparnasse station", "pharmacy"),
    # « De Paris à pizzeria » (production, Chouette): a ranked category is the category, the rank a qualifier
    ("Où se situent les 3 meilleures pizzerias de Paris", "pizza", "paris", "3 meilleures pizzerias"),
    ("les meilleures boulangeries à Lyon", "bakery", "lyon", "meilleures boulangeries"),
    ("best bakeries in Lyon", "bakery", "lyon", "the best bakeries"),
    ("top 5 restaurants à Lille", "restaurant", "lille", "top 5 restaurants"),
]
# names that start with a kind word: a name, never a category
MAPS_CATEGORY_NO: list[str] = [
    "gare de Lyon", "école des Mines", "Hôtel de Ville", "Pharmacie Lafayette", "boulangerie Paul",
    "restaurant Le Train Bleu", "Carrefour Market", "tour Eiffel", "banque de France", "musée d'Orsay",
    "Meilleurtaux", "Best Western", "Top Gun",
]  # fmt: skip


def category_ok(item) -> bool:
    """The parsers read the category and the anchor, and the model's own wording maps to the same category."""
    from birds.harness.tools.places import category

    text, kind, near, model_query = item
    got = _intent(text)
    args = (got.args or {}) if got is not None else {}
    parsed = got is not None and got.mode == "near" and args.get("query") == kind and _f(args.get("near")) == _f(near)
    mapped = (category(model_query) or ("",))[0] == kind
    return parsed and mapped


def category_touched(name: str) -> bool:
    """A name must stay a name: ``category`` is None."""
    from birds.harness.tools.places import category

    return category(name) is not None
