# BirdS — document de cadrage

_Un petit LLM d'entreprise, sobre et mesurable : « l'Ecosia des LLM »._
État au 20 novembre 2026. Les faits marqués **[Hub]** ont été vérifiés en direct sur Hugging Face ce jour ; ceux marqués **[presse]** viennent d'articles secondaires et restent à confirmer ; le reste est une recommandation.

---

## 1. Décisions proposées (résumé)

| Sujet                    | Décision proposée                                                                                                                    | Pourquoi                                                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Modèle de base           | **Qwen/Qwen3.5-4B** (Apache 2.0)                                                                                                     | Meilleur rapport capacité/taille vérifié : raisonnement `<think>` natif, appel d'outils natif, 262k tokens de contexte, 201 langues, vision incluse |
| Palier « éco »           | **Qwen/Qwen3.5-2B** distillé à partir de notre 4B                                                                                    | Même famille, même gabarit de prompt : un routeur envoie les tâches simples au 2B                                                                   |
| Challengers à départager | Granite-4.2-3B, Gemma-4-E2B                                                                                                          | Tous deux Apache 2.0 ; on tranche sur _notre_ jeu d'évaluation, pas sur les benchmarks éditeurs                                                     |
| Méthode d'entraînement   | Adaptation QLoRA/DoRA + distillation depuis un professeur open-weight                                                                | Coût et énergie divisés par un ordre de grandeur par rapport à un fine-tuning complet ; licences propres                                            |
| Couche agent             | **Harnais maison minimal, compatible MCP et API OpenAI** ; OpenClaw et Hermes Agent comme _cibles de compatibilité_, pas comme socle | OpenClaw est conçu pour de gros modèles (≥ 64k de contexte utile) et a un historique sécurité lourd                                                 |
| Diapositives             | Le modèle écrit un plan structuré (Markdown/JSON), un moteur déterministe produit le PPTX                                            | Un petit modèle est fiable sur de la structure, pas sur du XML PowerPoint                                                                           |
| Mesure d'impact          | Énergie **mesurée** par requête (Wh), convertie en gCO₂e et en €                                                                     | C'est le cœur de la promesse « Ecosia » : des chiffres réels, pas des estimations marketing                                                         |
| Langues                  | Français et anglais en priorité                                                                                                      | À confirmer (§ 9)                                                                                                                                   |

---

## 2. Choix du modèle de base

### 2.1 Candidats vérifiés

| Modèle                     | Paramètres [Hub]                    | Licence [Hub] | Contexte | Raisonnement   | Outils | Remarques                                                                                                |
| -------------------------- | ----------------------------------- | ------------- | -------- | -------------- | ------ | -------------------------------------------------------------------------------------------------------- |
| **Qwen/Qwen3.5-4B**        | 4,66 Md (encodeur vision inclus)    | Apache 2.0    | 262 144  | natif          | natif  | Architecture hybride Gated DeltaNet + attention ; 58,6 M de téléchargements ; version `-Base` disponible |
| Qwen/Qwen3.5-2B            | 2,27 Md                             | Apache 2.0    | 262 144  | natif          | natif  | Même famille ; nettement plus faible en connaissances (MMLU-Pro 55,3 sans raisonnement, chiffre éditeur) |
| Qwen/Qwen3.5-0.8B          | 0,87 Md                             | Apache 2.0    | —        | natif          | natif  | Trop juste pour de l'agentique généraliste ; utile comme routeur/classifieur                             |
| ibm-granite/granite-4.2-3b | 3,66 Md                             | Apache 2.0    | 128k     | natif, 3 modes | natif  | Texte seul, 12 langues testées dont le français, positionnement entreprise, sorti le 25/08/2026          |
| google/gemma-4-E2B-it      | 5,12 Md au total (« 2B effectifs ») | Apache 2.0    | —        | —              | —      | Multimodal y compris audio ; versions QAT 4 bits officielles                                             |
| google/gemma-4-E4B-it      | 8,0 Md au total                     | Apache 2.0    | —        | —              | —      | Trop gros pour la cible « tout petit »                                                                   |
| HuggingFaceTB/SmolLM3-3B   | 3,08 Md                             | Apache 2.0    | —        | double mode    | oui    | Recette d'entraînement publique très utile comme référence méthodologique ; modèle de 2025, dépassé      |

Écartés : Phi-4-mini (MIT, pas Apache, génération précédente), les modèles à `custom_code` récents et peu éprouvés (Spark-X2.6-4B, Raon-1-nano), et les familles plus récentes de Qwen (3.6, 3.8) qui **n'existent pas en petite taille** — le plus petit Qwen3.8 ouvert fait 27 Md.

### 2.2 Pourquoi Qwen3.5-4B

1. **Il a déjà les trois capacités demandées** : raisonnement, appel d'outils, long contexte. On adapte, on n'apprend pas de zéro. L'éditeur indique un entraînement par renforcement sur des environnements d'agents, ce qui est précisément notre usage.
2. **La vision est incluse** : lire une capture d'écran, un PDF scanné, une diapositive existante, sans second modèle.
3. **Une famille cohérente** (0.8B / 2B / 4B / 9B) : même tokenizer, même gabarit de conversation. On peut router et distiller à l'intérieur de la famille sans rien réécrire.
4. **Écosystème** : GGUF, MLX, WebGPU, vLLM déjà disponibles ; OpenClaw cite lui-même Qwen3.5 4B comme option locale **[presse]**.
5. **Professeur de la même lignée** : Qwen3.8-27B est en Apache 2.0, donc les données synthétiques qu'il produit sont libres de droits d'usage.

### 2.3 Ce qui n'est pas encore prouvé

- Les scores affichés sont ceux de l'éditeur. **Aucun benchmark indépendant sur nos tâches** (mails, comptes rendus, diapositives, français professionnel) n'a été trouvé.
- Aucune source ne mesure la fiabilité d'appel d'outils d'un modèle de 4 Md en conditions réelles ; les guides d'agents recommandent 9 Md et plus **[presse]**. C'est le risque principal du projet, et la raison d'être du fine-tuning.

**Conséquence : la première étape technique est un banc d'essai** (§ 7, phase 0) qui compare Qwen3.5-4B, Qwen3.5-2B, Granite-4.2-3B et Gemma-4-E2B _avant_ tout entraînement. Si Granite gagne sur le français et les outils, on change de base : le reste du plan ne bouge pas.

---

## 3. Stratégie d'entraînement

### 3.1 Principes

- **Évaluer d'abord.** Le jeu d'évaluation est écrit avant les données d'entraînement et n'y entre jamais.
- **Adapter, ne pas réentraîner.** QLoRA/DoRA sur les couches d'attention et MLP, encodeur vision gelé. Fine-tuning complet seulement si l'adaptateur plafonne.
- **Garder le format natif.** Même gabarit de conversation, mêmes balises `<think>` et `<tool_call>` que le modèle de base. Changer de format détruit ce que le modèle sait déjà faire.
- **Préserver le raisonnement.** Mélanger des exemples avec et sans trace de raisonnement ; entraîner uniquement sur du « sans raisonnement » fait perdre la capacité. Proportion de départ : environ 1/3 avec raisonnement, à ajuster par mesure.
- **Peu de données, très propres.** Pour un adaptateur, 100 à 300 k exemples bien filtrés battent des millions d'exemples bruités. Dédoublonnage, filtrage par langue, validation de schéma JSON des appels d'outils, suppression des données personnelles.
- **Co-concevoir modèle et outils.** Le modèle est entraîné sur _nos_ schémas d'outils exacts (§ 5). C'est l'avantage qu'un petit modèle spécialisé a sur un gros modèle généraliste.

### 3.2 Adapter les données au raisonnement

La plupart des jeux bureautiques n'ont pas de trace de raisonnement. Trois traitements :

1. **Tâches simples (reformulation, mail court, résumé)** : pas de raisonnement. On apprend au modèle à _ne pas_ réfléchir quand c'est inutile — c'est aussi le premier levier d'économie d'énergie (une réponse raisonnée coûte de l'ordre de 20 fois une réponse directe, d'après les mesures publiées sur des modèles Qwen).
2. **Tâches à étapes (outils, recherche web, tableaux, plan de présentation)** : trace courte générée par le professeur open-weight, puis vérifiée (l'appel d'outil est-il valide ? la réponse finale est-elle correcte ?). On ne garde que les exemples vérifiés.
3. **Refus et incertitude** : exemples où la bonne réponse est « l'information n'est pas dans les documents » ou « je dois chercher ». Indispensable pour un usage entreprise.

### 3.3 Données synthétiques

Les trous du catalogue ouvert (français professionnel, diapositives, nos outils) sont comblés par génération avec **Qwen3.8-27B ou gpt-oss-120b** (tous deux Apache 2.0), jamais avec une API fermée dont les conditions restreignent l'entraînement de modèles concurrents. Chaque exemple synthétique est validé automatiquement, et un échantillon est relu à la main.

### 3.4 Exécution sur Hugging Face

- **Hugging Face Jobs** avec scripts `uv` autonomes, TRL + PEFT, suivi Trackio, adaptateurs et jeux de données versionnés sur le Hub sous le compte `adubrou`.
- **CodeCarbon** activé sur chaque job : l'énergie d'entraînement est publiée dans la fiche du modèle.
- Ordre de grandeur attendu pour un adaptateur sur un modèle de 4 Md et 200 k exemples : quelques heures à une ou deux dizaines d'heures sur un seul GPU de 24 Go. **Estimation à valider** par un essai de 1 000 exemples avant de lancer la vraie passe.
- Sorties : poids fusionnés, GGUF Q4_K_M et Q8, adaptateur seul.

---

## 4. Données

Tous les dépôts cités ont été vérifiés sur le Hub le 20/11/2026 (existence, licence affichée, taille). Les licences sont celles de l'étiquette du Hub ; elles restent à relire source par source avant publication du modèle.

### 4.1 Mélange v0 — ce qu'on assemble en premier

Cible : **environ 200 000 exemples**, uniquement des sources permissives et déjà au bon format ou presque. C'est volontairement petit : on entraîne vite, on mesure, on complète.

| Compétence                         | Source                                                                                                 | Licence          | Part v0 | Travail de préparation                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------- | ------- | ------------------------------------------ |
| Appel d'outils MCP                 | `Agent-Ark/Toucan-1.5M` (1,5 M, professeurs open-weight, exécutions MCP réelles)                       | Apache 2.0       | 40 k    | Échantillonner sur les scores du juge      |
| Appel d'outils + raisonnement      | `nvidia/Nemotron-SFT-Agentic-v4` (635 k, `reasoning_content`)                                          | OpenMDW-1.1      | 25 k    | Licence non standard : relecture juridique |
| Quand appeler, demander, refuser   | `nvidia/When2Call` (train), `MadeAgents/xlam-irrelevance-7.5k`                                         | CC-BY-4.0        | 15 k    | Garder le split `test` pour l'évaluation   |
| Format natif `<tool_call>`         | `NousResearch/hermes-function-calling-v1` (11,6 k, dont mode JSON)                                     | Apache 2.0       | 10 k    | Aucun                                      |
| Trajectoires d'agent longues       | `lambda/hermes-agent-reasoning-traces` (14,7 k, navigateur, terminal, planification)                   | Apache 2.0       | 10 k    | Tronquer les très longues                  |
| Recherche approfondie              | `ScienceOne-AI/S1-DeepResearch-15k`, `FractalAIResearch/DeepResearch-SFT`                              | Apache 2.0 / MIT | 8 k     | Filtrer l'anglais                          |
| Réponse ancrée + citations         | `glaiveai/RAG-v1` (50 k), `LiquidAI/grounded-qa` (4 k, 16 langues, moitié sans réponse)                | Apache 2.0       | 15 k    | Aucun                                      |
| Réponse ancrée en français + refus | `CATIE-AQ/frenchQA` (200 k, avec questions sans réponse)                                               | CC-BY-4.0        | 10 k    | Mise au format conversation                |
| Réécriture, ton, résumé            | `HuggingFaceTB/smoltalk` (`smol-rewrite`, `smol-summarize`), `grammarly/coedit`                        | Apache 2.0       | 25 k    | Aucun                                      |
| Conversation générale courte       | `HuggingFaceTB/smol-smoltalk`                                                                          | Apache 2.0       | 15 k    | Aucun                                      |
| Français général                   | `CohereLabs/aya_dataset` (filtre `fra`, écrit par des humains)                                         | Apache 2.0       | 5 k     | Filtre langue                              |
| Raisonnement                       | `open-thoughts/OpenThoughts3-1.2M`, `glaiveai/reasoning-v1-20m`, `HuggingFaceH4/Multilingual-Thinking` | Apache 2.0       | 12 k    | Petit échantillon, traces courtes          |
| Tableaux et SQL                    | `LipengCS/Table-GPT`, `gretelai/synthetic_text_to_sql`                                                 | MIT / Apache 2.0 | 10 k    | Aucun                                      |
| Extraction structurée              | `LiquidAI/structured-extraction` (6 k, 16 langues)                                                     | Apache 2.0       | 5 k     | Aucun                                      |
| Diapositives                       | `Benitoow/OfficeSmith-PPTX-IR` (958, FR/EN, brief → JSON de présentation)                              | Apache 2.0       | 1 k     | Aligner sur notre schéma `make_slides`     |

Total : ≈ 205 k. Environ un tiers porte une trace de raisonnement (outils, agents, raisonnement), le reste non.

### 4.2 Réserve pour la v1

| Usage                    | Source                                                           | Licence          | Remarque                                                  |
| ------------------------ | ---------------------------------------------------------------- | ---------------- | --------------------------------------------------------- |
| Mails FR/EN/DE/IT        | `sinabis-group/sinabis-100k-synthetic-emails`                    | CC-BY-4.0        | Mails bruts : à transformer en tâches « écris / réponds » |
| Présentations            | `sinabis-group/sinabis-100k-synthetic-pptx` (24 langues)         | CC-BY-4.0        | Fichiers PPTX : en dériver des paires plan → diapositives |
| Documents, classeurs     | `sinabis-group/sinabis-100k-synthetic-docx`, `…-xlsx`            | CC-BY-4.0        | Seule source permissive avec formules ; tâches à dériver  |
| Documents financiers FR  | `gretelai/synthetic_pii_finance_multilingual` (56 k, 6 langues)  | Apache 2.0       | Extraction, résumé, masquage de données personnelles      |
| Raisonnement en français | `nvidia/Nemotron-Post-Training-Dataset-v2`, `PleIAs/SYNTH`       | CC-BY-4.0        | Accès à demander pour le premier                          |
| Support client           | `bitext/*` (12 verticales)                                       | CDLA-Sharing-1.0 | Anglais, très gabarisé : plafonner la part                |
| Sorties structurées      | `nvidia/Nemotron-RL-Instruction-Following-Structured-Outputs-v2` | CC-BY-4.0        | Format RL : cibles à générer et valider                   |
| Navigation web           | `osunlp/Mind2Web`                                                | CC-BY-4.0        | HTML brut : à réécrire en appels d'outils                 |
| Synthétiques non audités | `stindardlogic/*-sft-100k` (mails, réunions, extraction)         | Apache 2.0       | Générateur non divulgué : contrôle qualité avant usage    |

### 4.3 Exclus

- **Non commercial** : `Salesforce/APIGen-MT-5k`, `McGill-NLP/WebLINX`, `Alibaba-NLP/Open-DeepResearch`, `huuuyeah/meetingbank`, `knkarthick/dialogsum`, `HuggingFaceH4/no_robots`, `a-m-team/AM-DeepSeek-R1-Distilled-1.4M`.
- **Sans licence ou licence héritée gênante** : `corbt/enron-emails` et `Yale-LILY/aeslc` (Enron, données personnelles réelles), `microsoft/ms_marco`, `zai-org/AgentInstruct`, `wwh0411/MCP-Flow`, `argilla/FinePersonas-Synthetic-Email-Conversations` (licence Llama 3.1).
- **Distillés d'API fermées** : `teknium/OpenHermes-2.5`, `jpacifico/French-Alpaca-dataset-Instruct-110K` (GPT-3.5), `lightblue/tagengo-gpt4`, et tous les jeux « Claude / Opus / Fable reasoning » en tendance.
- **Contamination d'évaluation** : `interstellarninja/hermes_reasoning_tool_use` (aligné sur BFCL v3) et les jeux dérivés de τ²-bench restent hors entraînement tant que ces benchmarks servent à nous mesurer.

### 4.4 Trous à combler par génération synthétique

Aucune source ouverte et permissive n'existe pour ces compétences, qui sont pourtant le cœur du produit. Génération avec un professeur open-weight (§ 3.3), par ordre de priorité :

1. **Mails professionnels en français** — écrire, répondre, relancer, changer de ton. Cible v1 : 15 k.
2. **Recherche web + lecture de page + réponse citée**, dans notre format d'outils, FR/EN, avec reprise après échec d'un outil. Cible : 15 k.
3. **Plan → diapositives** dans notre schéma `make_slides`, FR/EN. Cible : 10 k (amorcé par OfficeSmith et sinabis-pptx).
4. **Comptes rendus de réunion, notes, rapports en français**, correction et reformulation en français. Cible : 10 k.
5. **Appel d'outils en français** — traduction et adaptation d'un échantillon de Toucan. Cible : 10 k.
6. **Formules de tableur** — génération et explication, à partir des classeurs sinabis. Cible : 5 k.

### 4.5 Évaluation (jamais dans l'entraînement)

| Compétence     | Benchmark                                                                                           |
| -------------- | --------------------------------------------------------------------------------------------------- |
| Appel d'outils | `gorilla-llm/Berkeley-Function-Calling-Leaderboard`, `nvidia/When2Call` (test), `ScaleAI/MCP-Atlas` |
| Agent web      | `Tevatron/browsecomp-plus` (corpus fixe, MIT), `gaia-benchmark/GAIA`                                |
| Structure      | `epfl-dlab/JSONSchemaBench`, `KAKA22/SpreadsheetBench-v2`                                           |
| Français       | `le-leadboard/IFEval-fr`, `AgentPublic/piaf`, `LiquidAI/grounded-qa` (test, lignes françaises)      |
| Métier         | Jeu maison de 300 cas (§ 7, phase 0) — le seul qui mesure vraiment le produit                       |

---

## 5. Couche agent : OpenClaw ou autre chose ?

### 5.1 Constat

|                     | OpenClaw                                                                                                                                       | Hermes Agent                                                             | Harnais maison                       |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------ |
| Licence             | MIT **[presse]**                                                                                                                               | ouverte                                                                  | la nôtre                             |
| Conçu pour          | gros modèles, contexte ≥ 64k **[presse]**                                                                                                      | gros modèles, 64k recommandés **[presse]**                               | notre modèle de 4 Md                 |
| Sécurité par défaut | exécution sur l'hôte sans confirmation, bac à sable désactivé ; plus de cent CVE recensées, chiffres divergents selon les sources **[presse]** | filtrage de commandes, mais le modèle peut s'auto-approuver **[presse]** | liste blanche d'outils, pas de shell |
| Coût en tokens      | invite système volumineuse, dizaines d'outils                                                                                                  | idem                                                                     | invite courte, 6 à 8 outils          |

Un petit modèle se dégrade vite avec une longue invite système et un grand nombre d'outils. Brancher BirdS tel quel dans OpenClaw donnerait une mauvaise expérience **et** annulerait le gain énergétique (chaque requête traînerait des dizaines de milliers de tokens de contexte).

### 5.2 Recommandation

**Un harnais minimal à nous, qui parle les standards.**

- Serveur d'inférence exposant l'**API compatible OpenAI** : BirdS reste utilisable depuis OpenClaw, Hermes Agent, Open WebUI ou n'importe quel client. On teste cette compatibilité, on ne s'en sert pas comme socle.
- Outils exposés en **MCP**, en petit nombre :
  - `web_search` — moteur auto-hébergé (SearXNG) ou API de recherche ;
  - `read_page` — récupération et conversion en Markdown propre (extraction déterministe, sans modèle) ;
  - `read_file` — PDF, DOCX, XLSX, PPTX vers texte ;
  - `draft_email` — brouillon structuré (objet, corps, ton), jamais d'envoi sans validation humaine ;
  - `make_slides` — plan structuré vers PPTX ;
  - `make_document` / `make_sheet` — idem pour DOCX et XLSX ;
  - `run_python` — bac à sable isolé, pour les calculs et les tableaux.
- **Navigation complète (clics, formulaires) en option**, via Playwright dans un conteneur isolé, activée seulement si la lecture de page ne suffit pas. C'est l'action la plus coûteuse et la plus risquée.
- **Garde-fous** : contenu web traité comme non fiable (les instructions trouvées dans une page ne sont jamais exécutées), confirmation humaine pour toute action sortante, journal complet des appels d'outils.

---

## 6. Plateforme et interface

### 6.1 Ce que voit l'utilisateur

- Conversation classique, avec les étapes de l'agent visibles (recherche, pages lues, sources citées).
- Résultats bureautiques téléchargeables : mail, DOCX, PPTX, XLSX.
- **Un compteur par réponse** : énergie (Wh), émissions (gCO₂e), coût (€), tokens, durée, modèle utilisé (2B ou 4B, raisonnement oui/non).
- **Un tableau de bord** par utilisateur et par organisation : consommation cumulée, répartition par type de tâche, part des requêtes servies par le petit palier, comparaison avec une référence « grand modèle » dont l'hypothèse et l'incertitude sont affichées.

### 6.2 Comment on mesure

- GPU : puissance instantanée via NVML ; CPU : RAPL. Énergie d'une requête = puissance intégrée sur sa durée, répartie entre les requêtes simultanées, plus une part de la consommation au repos.
- Conversion carbone avec l'intensité du réseau électrique au moment de la requête (données ouvertes type RTE éCO2mix ou Electricity Maps).
- Les chiffres sont **mesurés** quand on maîtrise la machine, **estimés et étiquetés comme tels** sinon. On n'affiche jamais une estimation comme une mesure.

### 6.3 Leviers de sobriété, par ordre d'effet

1. **Raisonnement désactivé par défaut**, activé par le routeur ou par l'utilisateur.
2. **Cascade petit-d'abord** : le 2B répond, le 4B ne prend le relais que si nécessaire.
3. **Contexte court** : invite système minimale, peu d'outils, pages web nettoyées avant d'entrer dans le contexte.
4. **Quantification 4 bits** (GGUF Q4_K_M ou QAT) : mémoire divisée par quatre environ, perte de qualité à mesurer sur notre jeu d'évaluation.
5. **Cache de préfixe** et regroupement des requêtes côté serveur.
6. **Mise en veille** du serveur à l'arrêt d'activité ; hébergement dans une région à électricité bas carbone.
7. **Exécution locale possible** (poste de travail, WebGPU) pour les tâches simples : zéro centre de données.

### 6.4 Pile technique proposée

- Inférence : **llama.cpp** (poste, CPU, petit GPU) et **vLLM** (multi-utilisateurs).
- Passerelle : service léger qui route, mesure et journalise.
- Application web : front React, **Supabase** pour l'authentification, l'historique et les mesures d'usage.
- Déploiement : à décider (§ 9).

---

## 7. Feuille de route

**Chemin court vers un premier modèle.** Les phases 0 à 2 s'enchaînent sans attendre les données synthétiques : banc d'essai réduit (100 cas maison + BFCL), mélange v0 du § 4.1 tel quel, un adaptateur sur Qwen3.5-4B. Ce premier modèle ne saura pas encore bien écrire un mail en français ni produire des diapositives — il sert à valider toute la chaîne (données → entraînement → évaluation → GGUF) et à chiffrer le coût réel. Les compétences métier arrivent avec la v1 (§ 4.4).

| Phase                  | Contenu                                                                                                                                                                                           | Critère de passage                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **0. Banc d'essai**    | Jeu d'évaluation maison (≈ 300 cas FR/EN : mails, résumés, plans de diapositives, appels d'outils, recherche web, refus) + benchmarks publics ; mesure des 4 candidats bruts, en qualité et en Wh | Base choisie sur chiffres                                                |
| **1. Données**         | Assemblage, nettoyage, conversion au format natif, génération synthétique, publication du jeu sur le Hub                                                                                          | Jeu validé, licences tracées ligne par ligne                             |
| **2. Entraînement v0** | Essai sur 1 000 exemples, puis adaptateur complet sur HF Jobs                                                                                                                                     | Gain mesuré contre le modèle brut, aucune régression sur le raisonnement |
| **3. Agent**           | Harnais + outils MCP, tests de bout en bout (recherche → lecture → mail/diapositives)                                                                                                             | Taux de réussite cible sur les scénarios d'entreprise                    |
| **4. Plateforme**      | Interface, compteur par requête, tableau de bord                                                                                                                                                  | Mesures cohérentes avec un wattmètre de référence                        |
| **5. Palier éco**      | Distillation vers le 2B, routeur                                                                                                                                                                  | Part des requêtes servies par le 2B sans perte perçue                    |

Chaque changement de prompt, d'outil ou d'adaptateur est livré avec ses chiffres avant/après sur le jeu d'évaluation fixe.

---

## 8. Risques

| Risque                                                                    | Parade                                                                                                               |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Un modèle de 4 Md échoue sur les tâches agentiques longues                | Peu d'outils, tâches bornées, entraînement sur nos schémas ; repli documenté vers Qwen3.5-9B                         |
| Licences de données ambiguës (données distillées d'API fermées, CC-BY-NC) | Registre de provenance par source ; exclusion par défaut en cas de doute                                             |
| Perte du raisonnement ou du multilingue après adaptation                  | Mélange raisonné/non raisonné, adaptateur plutôt que réentraînement, tests de non-régression                         |
| Injection d'instructions via les pages web                                | Contenu web isolé, pas d'action sortante sans validation, pas de shell                                               |
| « Greenwashing » involontaire                                             | Mesures réelles, méthode publiée, incertitude affichée, périmètre explicite (inférence ; entraînement publié à part) |
| Qualité du français professionnel                                         | Données françaises dédiées + relecture humaine d'un échantillon                                                      |

---

## 9. Points à trancher

1. **Taille cible** : 4 Md comme modèle principal et 2 Md en palier éco (proposé), ou 2 Md seul pour une promesse « tout petit » plus radicale ?
2. **Langues** : français + anglais (proposé), ou périmètre européen plus large dès la v1 ?
3. **Hébergement** : uniquement dans le nuage, ou aussi installable chez le client / en local ?
4. **Budget d'entraînement** et plafond de dépense sur Hugging Face Jobs.
5. **Nom** du modèle et de la plateforme (BirdS par défaut).
