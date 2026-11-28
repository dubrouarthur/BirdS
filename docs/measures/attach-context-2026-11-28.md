# R1 — a document attached earlier no longer hijacks later turns (2026-11-28)

Fixed set: `tests/fixtures/attach_followups.json`, 10 two-turn conversations (turn 1 brings a meeting note and asks
about it; turn 2 is a general question for 6 of them, a question about the note for 4).

## Offline, what the model is given on turn 2 (`scripts/attach_context_bench.py`)

| turn 2 | « [Fichier joint] » in the message | « lecture de … » planned | web tools withheld | read_file offered |
| --- | --- | --- | --- | --- |
| general, before | 6/6 | 0/6 | 6/6 | 6/6 |
| general, after | **0/6** | 0/6 | **1/6** | 6/6 |
| about the note, before | 4/4 | 0/4 | 4/4 | 4/4 |
| about the note, after | **0/4** (the history notes it) | 0/4 | 4/4 | 4/4 |

Before, every later message was presented as « coming with » the file: the model read it first, answered « Le fichier
joint ne contient pas… » and the app showed « D'après : texte-colle-1.txt »; the web tools and result cards were
withheld as for a question about a document. The one general question that still withholds the web tools after is
« Combien font 17 fois 23 ? » (figures in the question, the existing routing rule).

## Live, production before the fix (`--live https://bird-s.vercel.app --only 3`, 6 generations)

| turn 2 (general) | answer |
| --- | --- |
| Quelle est la capitale de l'Australie ? | « Je n'ai pas accès au contenu du fichier joint… » |
| Donne-moi une recette simple de crêpes. | « Je n'ai pas accès au contenu du fichier joint… » |
| Explique la photosynthèse en deux phrases. | correct |

2/3 general follow-ups answered about the file. The live « after » needs this branch deployed (the bench takes
`--live <url>`); the offline numbers above are the gate (`tests/test_attach_context.py`).
