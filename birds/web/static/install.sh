#!/bin/sh
# Bird en local, en une commande :
#   curl -fsSL https://bird-s.vercel.app/install.sh | sh
#
# Ce que fait ce script, sans rien cacher :
#   1. vérifie python3 (3.10+), git et curl ;
#   2. récupère Bird dans ~/.bird/app (ou le met à jour) et l'installe dans un environnement Python à part ;
#   3. démarre le modèle avec vLLM sur http://127.0.0.1:8000 (sauf si un serveur tourne déjà ou si BIRD_VLLM_URL
#      désigne le vôtre) ;
#   4. démarre Bird sur http://127.0.0.1:8765, uniquement sur votre machine, et ouvre le navigateur.
# Rien n'est envoyé ailleurs : le modèle, vos messages et les outils tournent chez vous.
#
# Réglages (variables d'environnement, toutes facultatives) :
#   BIRD_MODEL      modèle Hugging Face à servir            (défaut : adubrou/Bird-S-4B)
#   HF_TOKEN        jeton Hugging Face si le modèle est privé
#   BIRD_VLLM_URL   un serveur compatible OpenAI déjà lancé (ex. http://127.0.0.1:8000/v1) : vLLM n'est pas installé
#   BIRD_PORT       port de Bird                             (défaut : 8765)
#   BIRD_HOME       dossier d'installation                   (défaut : ~/.bird)
#   BIRD_REPO       dépôt Git de Bird                        (défaut : https://github.com/dubrouarthur/BirdS.git)
#   BIRD_REF        branche ou version                       (défaut : ccr-f7b26c02-9v78gg)
# Arrêter : sh ~/.bird/stop.sh
set -eu

BIRD_HOME="${BIRD_HOME:-$HOME/.bird}"
BIRD_MODEL="${BIRD_MODEL:-adubrou/Bird-S-4B}"
BIRD_PORT="${BIRD_PORT:-8765}"
BIRD_REPO="${BIRD_REPO:-https://github.com/dubrouarthur/BirdS.git}"
BIRD_REF="${BIRD_REF:-ccr-f7b26c02-9v78gg}"
VLLM_PORT="${VLLM_PORT:-8000}"
APP="$BIRD_HOME/app"
VENV="$BIRD_HOME/venv"
LOGS="$BIRD_HOME/logs"

say() { printf '\033[1;34m›\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. prérequis
command -v curl >/dev/null 2>&1 || die "curl est requis."
command -v git >/dev/null 2>&1 || die "git est requis (https://git-scm.com)."
PY=""
for p in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$p"; break
  fi
done
[ -n "$PY" ] || die "Python 3.10 ou plus est requis (https://www.python.org)."
mkdir -p "$BIRD_HOME" "$LOGS"
ok "Prérequis : $($PY --version), git, curl"

# ---- 2. Bird
if [ -d "$APP/.git" ]; then
  say "Mise à jour de Bird…"
  git -C "$APP" fetch -q --depth 1 origin "$BIRD_REF" && git -C "$APP" checkout -q -B bird FETCH_HEAD
else
  say "Téléchargement de Bird…"
  git clone -q --depth 1 --branch "$BIRD_REF" "$BIRD_REPO" "$APP" \
    || die "Impossible de récupérer Bird depuis $BIRD_REPO (dépôt privé : vérifiez vos accès Git, ou définissez BIRD_REPO)."
fi
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r "$APP/requirements.txt" "uvicorn[standard]"
ok "Bird installé dans $APP"

up() { curl -fsS -m 3 "$1/models" >/dev/null 2>&1; }

# ---- 3. le modèle (vLLM)
if [ -n "${BIRD_VLLM_URL:-}" ]; then
  BASE_URL="${BIRD_VLLM_URL%/}"
  up "$BASE_URL" || die "Aucun serveur compatible OpenAI ne répond sur $BASE_URL."
  ok "Serveur du modèle existant : $BASE_URL"
else
  BASE_URL="http://127.0.0.1:$VLLM_PORT/v1"
  if up "$BASE_URL"; then
    ok "vLLM tourne déjà sur $BASE_URL"
  else
    command -v nvidia-smi >/dev/null 2>&1 \
      || say "Pas de carte graphique NVIDIA détectée : vLLM sera lent ou indisponible. Vous pouvez désigner un serveur existant avec BIRD_VLLM_URL."
    if ! "$VENV/bin/python" -c 'import vllm' >/dev/null 2>&1; then
      say "Installation de vLLM (quelques minutes la première fois)…"
      "$VENV/bin/python" -m pip install -q vllm || die "L'installation de vLLM a échoué (voir https://docs.vllm.ai)."
    fi
    say "Démarrage du modèle $BIRD_MODEL avec vLLM…"
    # HF_TOKEN, s'il est défini, est lu par vLLM depuis l'environnement : il n'est jamais écrit sur le disque ni affiché
    nohup "$VENV/bin/vllm" serve "$BIRD_MODEL" --host 127.0.0.1 --port "$VLLM_PORT" --served-model-name bird \
      >"$LOGS/vllm.log" 2>&1 &
    echo $! >"$BIRD_HOME/vllm.pid"
    i=0
    until up "$BASE_URL"; do
      i=$((i + 1))
      [ $i -le 180 ] || die "vLLM ne répond pas après 15 min. Journal : $LOGS/vllm.log"
      kill -0 "$(cat "$BIRD_HOME/vllm.pid")" 2>/dev/null || die "vLLM s'est arrêté. Journal : $LOGS/vllm.log"
      sleep 5
    done
    ok "Modèle prêt sur $BASE_URL"
  fi
fi
MODEL_ID="$(curl -fsS -m 5 "$BASE_URL/models" | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])')"

# ---- 4. Bird, sur votre machine uniquement
cd "$APP"
if [ -f scripts/bird_local.py ]; then
  set -- "$VENV/bin/python" scripts/bird_local.py --vllm-url "$BASE_URL" --port "$BIRD_PORT"
else
  set -- "$VENV/bin/python" scripts/serve.py --base-url "$BASE_URL" --model "$MODEL_ID" --api-key local \
    --host 127.0.0.1 --port "$BIRD_PORT"
fi
nohup "$@" >"$LOGS/bird.log" 2>&1 &
echo $! >"$BIRD_HOME/bird.pid"
i=0
until curl -fsS -m 3 "http://127.0.0.1:$BIRD_PORT/api/health" >/dev/null 2>&1; do
  i=$((i + 1))
  [ $i -le 60 ] || die "Bird ne démarre pas. Journal : $LOGS/bird.log"
  kill -0 "$(cat "$BIRD_HOME/bird.pid")" 2>/dev/null || die "Bird s'est arrêté. Journal : $LOGS/bird.log"
  sleep 1
done

cat >"$BIRD_HOME/stop.sh" <<EOF
#!/bin/sh
for f in "$BIRD_HOME/bird.pid" "$BIRD_HOME/vllm.pid"; do
  [ -f "\$f" ] && kill "\$(cat "\$f")" 2>/dev/null; rm -f "\$f"
done
echo "Bird local arrêté."
EOF
chmod +x "$BIRD_HOME/stop.sh"

URL="http://127.0.0.1:$BIRD_PORT/"
ok "Bird tourne sur votre machine : $URL"
grep -m1 -i "code" "$LOGS/bird.log" 2>/dev/null || true # the pairing code of bird_local.py, when it prints one
echo "   Journaux : $LOGS   ·   Arrêter : sh $BIRD_HOME/stop.sh"
if command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
fi
