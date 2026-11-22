---
license: apache-2.0
language: [fr, en]
pipeline_tag: image-text-to-text
library_name: transformers
tags: [bird, small-language-model, frugal, green-ai, tool-calling, reasoning, french, enterprise]
---

<p align="center"><img src="assets/bird-icon.png" width="112" alt="Bird"></p>

<h1 align="center">Bird S 4B</h1>
<p align="center"><b>Petit par conviction.</b></p>

Bird est un assistant de travail de **4 milliards de paramètres**, en français et en anglais, conçu par
**Bird Models**.

Notre pari est simple : la course aux modèles toujours plus gros n'est pas la seule voie. Pour l'essentiel
du travail de bureau (un mail, un compte rendu, une synthèse, un tableau, une recherche), un petit modèle
bien entraîné suffit. Nous ne cherchons pas à faire plus gros. Nous cherchons à faire **petit et
performant**.

## Pourquoi petit

- **Sobre.** Moins de paramètres, c'est moins de calcul pour chaque réponse.
- **Accessible.** Bird tourne sur un seul GPU de 24 Go.
- **Franc.** Bird sait qu'il est petit. Il le dit, il signale quand il n'est pas sûr, et il vous invite à
  relire ce qui compte plutôt que d'inventer.

## Ce que Bird sait faire

Rédiger et reformuler, résumer, préparer une présentation, extraire des données en JSON, appeler des outils
(recherche web, lecture de pages et de fichiers, création de documents) et raisonner avant de répondre quand
la question le demande. Il répond dans votre langue, va droit au but et ignore les instructions cachées dans
les pages qu'il lit.

| Banc d'essai interne (score de 0 à 1) | Cas | Bird S 4B |
|---|---|---|
| Appel d'outils (BFCL) | 200 | 0,89 |
| Sortie JSON conforme à un schéma | 120 | 0,98 |
| Concision | 30 | 0,97 |
| Résistance aux instructions piégées | 24 | 1,00 |
| Répondre dans la langue de l'utilisateur | 40 | 1,00 |

Scores automatiques sur notre banc d'essai, dont les cas sont exclus de l'entraînement.

## Sobriété mesurée

| | |
|---|---|
| Génération | **0,36 Wh pour 1 000 tokens**, mesurés sur le GPU (1 × A10G 24 Go, 1 369 réponses) |
| Entraînement | **1,8 kWh**, mesurés sur le GPU (1 × L40S, 5 h 26) |

Mesures limitées au GPU, hors processeur et refroidissement. Nous publions ce que nous mesurons, rien de
plus.

## Utiliser Bird

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

tok = AutoTokenizer.from_pretrained("adubrou/Bird-S-4B")
model = AutoModelForCausalLM.from_pretrained("adubrou/Bird-S-4B", dtype="bfloat16", device_map="auto")

msgs = [{"role": "user", "content": "Rédige un mail de trois lignes pour décaler la réunion à vendredi 10 h."}]
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False,  # True pour raisonner
                              return_tensors="pt", return_dict=True).to(model.device)
out = model.generate(**ids, max_new_tokens=300)
print(tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
```

Nécessite `transformers` 5 ou plus. Raisonnement désactivé par défaut : c'est le mode le plus sobre.

## Licence

Apache 2.0. Bird S 4B est construit à partir d'un modèle ouvert publié sous la même licence, dont la notice
figure dans le fichier `LICENSE`.

---

**English.** Bird S 4B is a 4-billion-parameter work assistant (French and English) by Bird Models. We are not
trying to build bigger models: we build small, capable ones. Bird is frugal, runs on a single 24 GB GPU, and
is candid about its limits.
