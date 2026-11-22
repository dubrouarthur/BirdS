---
license: apache-2.0
base_model: Qwen/Qwen3.5-4B
base_model_relation: finetune
language: [fr, en]
pipeline_tag: image-text-to-text
library_name: transformers
tags: [bird, small-language-model, frugal, tool-calling, reasoning, french, enterprise]
---

# Bird S 4B — v1

**Bird** est un petit assistant de travail (français et anglais), construit à partir du modèle ouvert
[Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (Apache 2.0) puis spécialisé par Bird Models.
Sa raison d'être : offrir une alternative petite et sobre aux très grands modèles. Il le dit lui-même :
il fait plus d'erreurs qu'un grand modèle, mais il demande beaucoup moins de calcul.

> **État : v1.** Corrige la régression de v0 sur l'appel d'outils et remplace l'identité récitée par des
> conversations rédigées. La v0 reste disponible dans l'historique de ce dépôt.

## Ce que contient ce dépôt

Le modèle complet fusionné (même format que Qwen3.5-4B, encodeur d'images d'origine inchangé) et, dans
`adapter/`, l'adaptateur LoRA seul. Gabarit de conversation, raisonnement (`<think>`) et format d'appel
d'outils : ceux de Qwen3.5-4B, non modifiés.

## Résultats (banc d'essai interne, 1 369 cas, scores automatiques entre 0 et 1)

| Suite | Cas | Qwen3.5-4B | Bird v0 | Bird v1 |
|---|---|---|---|---|
| Identité Bird | 40 | 0,00 | 0,83 | **0,95** |
| Concision | 30 | 0,43 | 0,87 | **0,97** |
| **Appel d'outils (BFCL)** | 200 | 0,83 | 0,38 | **0,89** |
| Appeler, demander ou refuser (When2Call) | 150 | 0,57 | 0,58 | **0,67** |
| Sortie JSON conforme à un schéma | 120 | 0,97 | 0,97 | 0,98 |
| Instructions piégées dans un résultat d'outil | 24 | non mesuré | 1,00 | 1,00 |
| Répondre dans la langue de l'utilisateur | 40 | 1,00 | 1,00 | 1,00 |
| Ne pas appeler d'outil inutile (BFCL irrelevance) | 100 | 0,84 | 0,97 | 0,85 |
| Finance, mode raisonnement | 60 | 0,02 | 0,31 | 0,33 |
| Finance, calculs exacts | 175 | 0,37 | 0,21 | 0,27 |
| Questions en français sur document (PIAF) | 100 | 0,78 | 0,77 | 0,74 |
| Réponse ancrée ou « pas dans le document » | 150 | 0,91 | 0,88 | 0,83 |
| Appel d'outils, mode raisonnement (BFCL) | 60 | 0,90 | 0,67 | 0,73 |
| Choix du bon outil produit | 60 | 1,00 | 0,97 | 0,87 |
| Choix du bon outil produit, mode raisonnement | 60 | 1,00 | 0,97 | 0,90 |
| Moyenne des 11 suites communes sans raisonnement | | 0,70 | 0,77 | **0,82** |
| Moyenne des 3 suites en mode raisonnement | | 0,64 | 0,65 | 0,65 |

Par langue : anglais 0,75 → 0,79 ; français 0,63 → 0,68.

**Ce qui reste en dessous du modèle de base.**
- *Outils en mode raisonnement* : quand plusieurs appels sont attendus d'un coup, Bird n'en émet qu'un à la
  fois (les exemples d'appels parallèles de l'entraînement étaient sans raisonnement).
- *Choix du bon outil produit* : Bird appelle parfois un outil pour une demande simple (un calcul mental,
  une reformulation) à laquelle il devrait répondre directement.
- *Réponses ancrées et questions sur document* : léger recul (0,91 → 0,83 ; 0,78 → 0,74).
- *Calculs financiers* : toujours sous le modèle de base hors mode raisonnement.

Les scores sont déterministes et grossiers (présence d'un nombre, forme d'un appel, motifs de refus) ; ils
ne remplacent pas une relecture humaine. Le banc et les scoreurs sont dans le dépôt de code.

## Entraînement

| | |
|---|---|
| Méthode | LoRA en bf16 (pas de 4 bits), rang 32, alpha 32, sur les projections d'attention, d'attention linéaire et MLP du modèle de langage ; 60,9 M de paramètres entraînés (1,4 %) ; départ du modèle de base |
| Optimisation | AdamW, taux 2e-4, échauffement 5 %, décroissance cosinus, régularisation 0,01, lots de 8 192 tokens × 4, 1 époque (1 338 étapes) |
| Données | 33 558 conversations (39 M de tokens) : 34 % en français, 40 % avec raisonnement, 39 % avec outils |
| Perte d'évaluation | 0,896 → 0,683 (meilleur point : dernière étape) |
| Matériel | 1 × NVIDIA L40S (48 Go), 5 h 26 |
| Énergie | 1 787 Wh mesurés sur le GPU (nvidia-smi), hors CPU et refroidissement ; la v0 avait consommé 1 493 Wh |

Changements par rapport à v0 : ajout d'appels d'outils directs et parallèles
(Salesforce/xlam-function-calling-60k), forte réduction des exemples « demander une précision », et
2 176 conversations dans le ton de Bird rédigées par un modèle professeur ouvert (Qwen/Qwen3.8-27B,
Apache 2.0) puis filtrées automatiquement, à la place de la plupart des gabarits d'identité.

La perte n'est calculée que sur les tours de l'assistant qui suivent la dernière demande de l'utilisateur,
rendus par le gabarit officiel (mode raisonnement activé ou coupé selon l'exemple).

## Données et licences

Chaque conversation garde sa source et sa licence d'origine. Sources publiques : Agent-Ark/Toucan-1.5M,
NousResearch/hermes-function-calling-v1, lambda/hermes-agent-reasoning-traces,
ScienceOne-AI/S1-DeepResearch-15k, glaiveai/RAG-v1, glaiveai/reasoning-v1-20m, LiquidAI/grounded-qa,
LiquidAI/structured-extraction, HuggingFaceTB/smoltalk, smol-smoltalk et smoltalk2, grammarly/coedit,
CohereLabs/aya_dataset, open-thoughts/OpenThoughts3-1.2M, HuggingFaceH4/Multilingual-Thinking,
gretelai/synthetic_text_to_sql (Apache 2.0) ;
Salesforce/xlam-function-calling-60k (CC-BY 4.0) ; LipengCS/Table-GPT (MIT) ; nvidia/When2Call,
MadeAgents/xlam-irrelevance-7.5k, CATIE-AQ/frenchQA, nvidia/Nemotron-Post-Training-Dataset-v2, PleIAs/SYNTH,
sinabis-group/sinabis-100k-synthetic-emails, CATIE-AQ/smoltalk2_smolagents_toolcalling_french (CC-BY 4.0) ;
**nvidia/Nemotron-SFT-Agentic-v4 (OpenMDW 1.1, licence non standard à faire relire avant toute diffusion
publique)**. Données propres : conversations d'entreprise en français (mails, diapositives, finance),
identité et personnalité de Bird (gabarits et conversations rédigées par Qwen/Qwen3.8-27B), garde-fous
contre les instructions piégées.

Les jeux du banc d'essai (BFCL, When2Call test, PIAF, grounded-qa test, JSONSchemaBench) sont exclus de
l'entraînement.

## Limites

- Petit modèle : plus d'erreurs factuelles et de calcul qu'un grand modèle. Relire ce qui compte.
- Appels d'outils parallèles en mode raisonnement, réponses ancrées et calculs financiers : sous le modèle de base (voir plus haut).
- Les conversations de personnalité viennent d'un modèle professeur et n'ont pas été relues une par une.
- Pas d'accès au web ni aux fichiers sans un harnais qui exécute les outils.
- Mesures d'énergie limitées au GPU ; aucune comparaison chiffrée avec d'autres modèles n'est revendiquée.
- Évalué uniquement en français et en anglais.

## Utilisation

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("adubrou/Bird-S-4B")
model = AutoModelForCausalLM.from_pretrained("adubrou/Bird-S-4B", dtype="bfloat16", device_map="auto")
msgs = [{"role": "user", "content": "Qui es-tu ?"}]
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False,
                              return_tensors="pt", return_dict=True).to(model.device)
print(tok.decode(model.generate(**ids, max_new_tokens=200)[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
```

Nécessite `transformers` version 5 ou plus.
