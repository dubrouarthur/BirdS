---
license: apache-2.0
base_model: Qwen/Qwen3.5-4B
base_model_relation: finetune
language: [fr, en]
pipeline_tag: image-text-to-text
library_name: transformers
tags: [bird, small-language-model, frugal, tool-calling, reasoning, french, enterprise]
---

# Bird S 4B — v0

**Bird** est un petit assistant de travail (français et anglais), construit à partir du modèle ouvert
[Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (Apache 2.0) puis spécialisé par Bird Models.
Sa raison d'être : offrir une alternative petite et sobre aux très grands modèles. Il le dit lui-même :
il fait plus d'erreurs qu'un grand modèle, mais il demande beaucoup moins de calcul.

> **État : v0, première passe de validation — ne pas utiliser pour un agent à outils.**
> Cette version a appris l'identité et la concision, mais elle a **régressé sur l'appel d'outils**
> (elle demande une précision au lieu d'appeler). Une v1 corrigée est en cours d'entraînement.

## Ce que contient ce dépôt

Le modèle complet fusionné (même format que Qwen3.5-4B, encodeur d'images d'origine inchangé) et, dans
`adapter/`, l'adaptateur LoRA seul. Gabarit de conversation, raisonnement (`<think>`) et format d'appel
d'outils : ceux de Qwen3.5-4B, non modifiés.

## Résultats (banc d'essai interne, 1 369 cas, scores automatiques entre 0 et 1)

| Suite | Cas | Qwen3.5-4B | Bird v0 |
|---|---|---|---|
| Identité Bird | 40 | 0,00 | **0,83** |
| Concision | 30 | 0,43 | **0,87** |
| Ne pas appeler d'outil inutile (BFCL irrelevance) | 100 | 0,84 | **0,97** |
| Instructions piégées dans un résultat d'outil | 24 | non mesuré | 1,00 |
| Finance, mode raisonnement | 60 | 0,02 | 0,31 |
| Sortie JSON conforme à un schéma | 120 | 0,97 | 0,97 |
| Répondre dans la langue de l'utilisateur | 40 | 1,00 | 1,00 |
| Questions en français sur document (PIAF) | 100 | 0,78 | 0,77 |
| Réponse ancrée ou « pas dans le document » | 150 | 0,91 | 0,88 |
| Appeler, demander ou refuser (When2Call) | 150 | 0,57 | 0,58 |
| Choix du bon outil produit | 60 | 1,00 | 0,97 |
| Finance, calculs exacts | 175 | 0,37 | 0,21 |
| Appel d'outils, mode raisonnement (BFCL) | 60 | 0,90 | 0,67 |
| **Appel d'outils (BFCL)** | 200 | 0,83 | **0,38** |
| Moyenne des suites sans raisonnement | | 0,70 | 0,78 |

Par langue : anglais 0,75 → 0,66 ; français 0,63 → 0,71.

**Lecture.** Dans 87 des 95 cas d'appel d'outils perdus, Bird v0 pose une question de clarification là où le
modèle de base appelait directement l'outil. La cause est dans le mélange de données : une source ne
contenait que des exemples « demander » ou « refuser ». La personnalité est acquise mais récitée : les
données d'identité de v0 étaient des combinaisons d'un petit nombre de phrases.

Les scores sont déterministes et grossiers (présence d'un nombre, forme d'un appel, motifs de refus) ; ils
ne remplacent pas une relecture humaine. Le banc et les scoreurs sont dans le dépôt de code.

## Entraînement

| | |
|---|---|
| Méthode | LoRA en bf16 (pas de 4 bits), rang 32, alpha 32, sur les projections d'attention, d'attention linéaire et MLP du modèle de langage ; 60,9 M de paramètres entraînés (1,4 %) |
| Optimisation | AdamW, taux 2e-4, échauffement 5 %, décroissance cosinus, régularisation 0,01, lots de 8 192 tokens × 4 |
| Données | 39 540 conversations (48 M de tokens) : 38 % en français, 41 % avec raisonnement, 30 % avec outils |
| Durée | arrêté à l'étape 1 125 sur 1 646 ; point retenu : étape 1 000 (perte d'évaluation 0,857 → 0,636) |
| Matériel | 1 × NVIDIA L40S (48 Go), 4 h 30 |
| Énergie | 1 493 Wh mesurés sur le GPU (nvidia-smi), hors CPU et refroidissement |

La perte n'est calculée que sur les tours de l'assistant qui suivent la dernière demande de l'utilisateur,
rendus par le gabarit officiel (mode raisonnement activé ou coupé selon l'exemple).

## Données et licences

Chaque conversation garde sa source et sa licence d'origine. Sources publiques : Agent-Ark/Toucan-1.5M,
NousResearch/hermes-function-calling-v1, lambda/hermes-agent-reasoning-traces,
ScienceOne-AI/S1-DeepResearch-15k, glaiveai/RAG-v1, glaiveai/reasoning-v1-20m, LiquidAI/grounded-qa,
LiquidAI/structured-extraction, HuggingFaceTB/smoltalk, smol-smoltalk et smoltalk2, grammarly/coedit,
CohereLabs/aya_dataset, open-thoughts/OpenThoughts3-1.2M, HuggingFaceH4/Multilingual-Thinking,
gretelai/synthetic_text_to_sql (Apache 2.0) ; LipengCS/Table-GPT (MIT) ; nvidia/When2Call,
MadeAgents/xlam-irrelevance-7.5k, CATIE-AQ/frenchQA, nvidia/Nemotron-Post-Training-Dataset-v2, PleIAs/SYNTH,
sinabis-group/sinabis-100k-synthetic-emails, CATIE-AQ/smoltalk2_smolagents_toolcalling_french (CC-BY 4.0) ;
**nvidia/Nemotron-SFT-Agentic-v4 (OpenMDW 1.1, licence non standard à faire relire avant toute diffusion
publique)**. Données propres : conversations d'entreprise en français (mails, diapositives, finance),
identité Bird et garde-fous contre les instructions piégées.

Les jeux du banc d'essai (BFCL, When2Call test, PIAF, grounded-qa test, JSONSchemaBench) sont exclus de
l'entraînement.

## Limites

- Petit modèle : plus d'erreurs factuelles et de calcul qu'un grand modèle. Relire ce qui compte.
- v0 : appel d'outils dégradé (voir plus haut) ; calculs financiers plus faibles que le modèle de base.
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
