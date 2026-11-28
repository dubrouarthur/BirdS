#!/bin/sh
# Bird en local, en une commande :
#   curl -fsSL https://bird-s.vercel.app/install.sh | sh
#
# Ce que fait ce script, sans rien cacher :
#   1. vérifie python3 (3.10+), git et curl ;
#   2. récupère Bird dans ~/.bird/app (ou le met à jour) et l'installe dans son environnement Python (~/.bird/venv) ;
#   3. installe vLLM dans un second environnement (~/.bird/vllm-venv), vous connecte à Hugging Face (hf auth login)
#      si besoin, et sert le modèle sur http://127.0.0.1:8000 (sauf si un serveur tourne déjà ou si BIRD_VLLM_URL
#      désigne le vôtre), puis lui pose une première question ;
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
# Windows : irm https://bird-s.vercel.app/install.ps1 | iex   (PowerShell)
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

# couleurs dans un terminal seulement (jamais de codes dans un journal), et jamais avec NO_COLOR
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then C_B='\033[1;34m'; C_G='\033[1;32m'; C_R='\033[1;31m'; C_0='\033[0m'
else C_B=''; C_G=''; C_R=''; C_0=''; fi
say() { printf "${C_B}›${C_0} %s\n" "$*"; }
ok() { printf "${C_G}✓${C_0} %s\n" "$*"; }
die() { printf "${C_R}✗${C_0} %s\n" "$*" >&2; exit 1; }

# ---- 0. l'oiseau : le logo de Bird en blocs (UTF-8), ou en ASCII simple ; couleur seulement dans un terminal
banner() {
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then b='\033[1;34m'; d='\033[2m'; r='\033[0m'; else b=''; d=''; r=''; fi
  printf '\n%b' "$b"
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8* | *utf8* | *UTF8* | *utf-8*) cat <<'BIRD'
       ▀█▄▄                    ▄
        ▀████▄▄              ▄██
         ▀██████▄           ████
          ████████▄        █████
           █████████▄     ██████
           ▀█████████▄    █████
            ██████████▄  ██████
             ██████████▄▄███████▄▄▄▄
              ███████████████████▀
               ▀███████████████▀
              ▄▄█████████████▀
          ▄▄████████████▀▀▀
     ▄▄▄█████████▀▀▀▀
   ▀▀▀▀▀▀▀▀▀
BIRD
      ;;
    *) cat <<'BIRD'
        __                       __
        \ `-.__            __.-' /
         `-.   `-.__  __.-'   .-'
            `-.     (o >    .-'
               `-.__/  \__.-'
                    \__/
BIRD
      ;;
  esac
  printf '%b\n   Bird  %b·  conçu en France%b\n' "$r" "$d" "$r"
  printf '%b   Votre IA, chez vous. Sans abonnement.%b\n\n' "$d" "$r"
}
banner

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
chmod 700 "$LOGS" # bird.log holds the pairing code of Bird local: this user only
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

# WSL : le disque Linux est un fichier sur le disque C: de Windows ; s'il est plein, c'est là qu'il faut faire de la place
in_wsl() { grep -qi microsoft /proc/version 2>/dev/null; }
space_hint() {
  if in_wsl; then echo "Libérez de la place sur le disque C: de Windows (Paramètres → Système → Stockage), puis relancez la même commande."
  else echo "Libérez de la place sur ce disque, puis relancez la même commande."; fi
}
# need_space DOSSIER GO QUOI : arrête tout de suite, avec la place qui manque, plutôt qu'après 10 minutes de téléchargement
need_space() {
  free_kb="$(df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ -n "$free_kb" ] || return 0
  free_gb=$((free_kb / 1048576))
  [ "$free_gb" -ge "$2" ] || die "Il faut environ $2 Go libres pour $3 ; il en reste $free_gb. $(space_hint)"
}
# gpu_detect : nom et mémoire (Mo) de la première carte NVIDIA, vides sans carte (sous WSL, nvidia-smi est dans /usr/lib/wsl/lib)
gpu_detect() {
  GPU_NAME=""; GPU_MB=0; NVSMI=""
  for c in nvidia-smi /usr/lib/wsl/lib/nvidia-smi; do
    if command -v "$c" >/dev/null 2>&1; then NVSMI="$c"; break; fi
  done
  [ -n "$NVSMI" ] || return 0
  line="$("$NVSMI" --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)"
  GPU_NAME="$(printf '%s' "$line" | cut -d, -f1 | sed 's/^ *//; s/ *$//')"
  GPU_MB="$(printf '%s' "$line" | cut -d, -f2 | tr -dc 0-9)"
  [ -n "$GPU_MB" ] || GPU_MB=0
}

# stop_previous_vllm : le vLLM d'un essai précédent de ce script (fichier vllm.pid, ou la même commande sur le même port)
stop_previous_vllm() {
  old="$(cat "$BIRD_HOME/vllm.pid" 2>/dev/null)"
  # tous les vLLM de ce compte, moteurs orphelins compris (« VLLM::EngineCore » d'un essai interrompu) : la carte et
  # la mémoire vive ne peuvent porter qu'un modèle
  pids="$old $(pgrep -u "$(id -u)" -f "vllm serve|VLLM::|vllm\.entrypoints" 2>/dev/null | grep -vx "$$")"
  found=""
  for p in $pids; do
    if kill -0 "$p" 2>/dev/null; then kill "$p" 2>/dev/null; found=1; fi
  done
  rm -f "$BIRD_HOME/vllm.pid"
  [ -n "$found" ] || return 0
  say "Arrêt des autres vLLM de cette machine (un seul modèle à la fois sur la carte)…"
  n=0
  for p in $pids; do
    while kill -0 "$p" 2>/dev/null && [ $n -lt 30 ]; do sleep 1; n=$((n + 1)); done
    kill -9 "$p" 2>/dev/null || true
  done
  return 0
}

# kill_orphan_engines : un moteur vLLM (« VLLM::… ») dont le serveur n'existe plus garde la mémoire de la carte ;
# ceux d'un serveur vivant ne sont jamais touchés
kill_orphan_engines() {
  ps -u "$(id -u)" -o pid= -o ppid= -o args= 2>/dev/null | while read -r pid ppid args; do
    case "$args" in VLLM::*) ;; *) continue ;; esac
    parent="$(ps -o args= -p "$ppid" 2>/dev/null)"
    case "$parent" in *vllm* | *VLLM*) ;; *) kill "$pid" 2>/dev/null && say "Moteur vLLM orphelin arrêté (pid $pid)." ;; esac
  done
  return 0
}

# ---- la barre de suivi du démarrage : les étapes réelles de vLLM, lues dans son journal
# stage LOG -> "pourcentage|libellé" de l'étape la plus avancée atteinte (jamais en arrière)
stage() {
  if grep -qiE "Application startup complete|Starting vLLM API server|Uvicorn running" "$1"; then echo "97|Ouverture du serveur"
  elif grep -qiE "Capturing (CUDA )?graph|cuda ?graph|torch\.compile|Compiling" "$1"; then echo "85|Optimisation pour votre carte"
  elif grep -qiE "KV cache|GPU blocks|Memory profiling|memory profiling" "$1"; then echo "72|Réservation de la mémoire"
  elif grep -qiE "Loading weights took|Model loading took|Loading safetensors.*100%" "$1"; then echo "62|Modèle chargé sur la carte"
  elif grep -qiE "Loading safetensors|Starting to load model|Loading model" "$1"; then echo "45|Chargement sur la carte graphique"
  elif grep -qiE "Downloading|Fetching [0-9]+ files|\.safetensors.*[0-9]+%" "$1"; then echo "15|Téléchargement du modèle (la première fois)"
  else echo "5|Démarrage de vLLM"; fi
}
bar() {  # bar POURCENT LIBELLÉ SECONDES
  w=28; f=$(($1 * w / 100)); e=$((w - f))
  full=$(printf '%*s' "$f" '' | sed 's/ /█/g'); empty=$(printf '%*s' "$e" '' | sed 's/ /░/g')
  t="$(($3 / 60)) min $(($3 % 60)) s"
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then printf '\r\033[K  \033[1;34m%s\033[0;2m%s\033[0m %3d %%  %s  \033[2m%s\033[0m' "$full" "$empty" "$1" "$2" "$t"
  elif [ -t 1 ]; then printf '\r  %s%s %3d %%  %s  %s   ' "$full" "$empty" "$1" "$2" "$t"
  else printf '  [%s%s] %3d %%  %s  (%s)\n' "$full" "$empty" "$1" "$2" "$t"; fi
}
wait_model() {
  i=0; best=0; last=""
  until up "$BASE_URL"; do
    kill -0 "$(cat "$BIRD_HOME/vllm.pid")" 2>/dev/null || { [ -t 1 ] && echo; die "vLLM s'est arrêté : $(vllm_reason). Journal : $LOGS/vllm.log"; }
    st="$(stage "$LOGS/vllm.log")"; pc="${st%%|*}"; lb="${st#*|}"
    if [ "$pc" -gt "$best" ]; then best=$pc; fi
    # sans terminal (journal, WSL redirigé) : une ligne par étape, pas une par seconde
    if [ -t 1 ] || [ "$lb" != "$last" ]; then bar "$best" "$lb" "$i"; last="$lb"; fi
    [ $i -le 1800 ] || { [ -t 1 ] && echo; die "vLLM ne répond pas après 30 min. Journal : $LOGS/vllm.log"; }
    sleep 2; i=$((i + 2))
  done
  bar 100 "Prêt" "$i"
  if [ -t 1 ]; then echo; fi
}
# la raison d'un arrêt de vLLM, en une phrase (sinon la dernière ligne du journal)
vllm_reason() {
  if grep -qiE "out of memory|CUDA out of memory|insufficient.*memory" "$LOGS/vllm.log"; then echo "mémoire de la carte insuffisante (fermez les jeux et applications 3D, puis relancez)"
  elif grep -qiE "401|403|gated|Access to model|not authorized|Repository Not Found" "$LOGS/vllm.log"; then echo "accès au modèle refusé par Hugging Face (connectez-vous avec un compte autorisé : hf auth login)"
  elif grep -qiE "No space left" "$LOGS/vllm.log"; then echo "disque plein. $(space_hint)"
  elif grep -qiE "No CUDA GPUs|CUDA driver|libcuda|nvidia driver" "$LOGS/vllm.log"; then echo "pilote NVIDIA introuvable (mettez à jour le pilote ; sous Windows, celui de Windows suffit pour WSL)"
  else tail -n 1 "$LOGS/vllm.log" | cut -c1-200; fi
}

install_failed() {
  rm -rf "$VLLM_VENV" "${TMPDIR:-}"  # rendre la place prise par l'essai
  if grep -q "No space left" "$LOGS/vllm-install.log" 2>/dev/null; then
    die "Disque plein pendant l'installation de vLLM (environ 25 Go nécessaires). $(space_hint)"
  fi
  die "L'installation de vLLM a échoué. Détail : $LOGS/vllm-install.log"
}

# ---- 3. le modèle (vLLM)
GPU_NAME=""; GPU_MB=0; NVSMI=""; VLLM_ARGS=""
if [ -n "${BIRD_VLLM_URL:-}" ]; then
  BASE_URL="${BIRD_VLLM_URL%/}"
  up "$BASE_URL" || die "Aucun serveur compatible OpenAI ne répond sur $BASE_URL."
  ok "Serveur du modèle existant : $BASE_URL"
else
  BASE_URL="http://127.0.0.1:$VLLM_PORT/v1"
  # un vLLM qui sert un AUTRE modèle sur ce port : l'arrêter, puis démarrer Bird
  served="$(curl -fsS -m 3 "$BASE_URL/models" 2>/dev/null | grep -o '"id": *"[^"]*"' | head -n 1 | sed 's/.*"\([^"]*\)"$/\1/')"
  if [ -n "$served" ] && [ "$served" != "$BIRD_MODEL" ]; then
    say "Un autre modèle ($served) occupe le port $VLLM_PORT."
    stop_previous_vllm
  fi
  kill_orphan_engines
  if up "$BASE_URL"; then
    ok "vLLM tourne déjà sur $BASE_URL"
    gpu_detect  # pour mesurer l'empreinte sur la carte
  else
    # vLLM sert le modèle sur la carte graphique NVIDIA (CUDA ; sous WSL, via le pilote NVIDIA de Windows).
    # Sans carte : on ne télécharge pas 10 Go qui ne démarreraient pas ; un serveur local déjà lancé convient.
    gpu_detect
    if [ -z "$GPU_NAME" ]; then
      for alt in http://127.0.0.1:1234/v1 http://127.0.0.1:11434/v1; do
        if up "$alt"; then BASE_URL="$alt"; ok "Serveur du modèle trouvé : $alt (LM Studio / Ollama)"; break; fi
      done
      [ "$BASE_URL" != "http://127.0.0.1:$VLLM_PORT/v1" ] || die "Aucune carte graphique NVIDIA détectée : vLLM a besoin d'une carte NVIDIA (pilote à jour ; sous Windows, WSL 2). Sans carte, lancez un serveur compatible OpenAI (LM Studio, Ollama…) puis relancez avec BIRD_VLLM_URL=http://127.0.0.1:1234/v1."
    fi
  fi
  if [ -n "$GPU_NAME" ] && ! up "$BASE_URL"; then
    say "Carte graphique : $GPU_NAME ($((GPU_MB / 1024)) Go) — le modèle tournera dessus."
    # réglages selon la mémoire de la carte : le modèle (~8 Go) et son contexte doivent y tenir
    if [ "$GPU_MB" -lt 6000 ]; then
      die "La carte $GPU_NAME a $((GPU_MB / 1024)) Go : il en faut au moins 6 pour le modèle. Utilisez un serveur existant avec BIRD_VLLM_URL."
    elif [ "$GPU_MB" -lt 11000 ]; then
      VLLM_ARGS="--quantization fp8 --max-model-len 8192"  # poids en 8 bits (~4 Go) : tient sur 8 Go
    elif [ "$GPU_MB" -lt 20000 ]; then
      VLLM_ARGS="--max-model-len 16384"
    else
      VLLM_ARGS=""
    fi
    # vLLM dans son propre environnement : ses dépendances (torch, CUDA) ne touchent jamais celles de Bird
    VLLM_VENV="$BIRD_HOME/vllm-venv"
    if ! "$VLLM_VENV/bin/python" -c 'import vllm' >/dev/null 2>&1; then
      # vLLM (torch + CUDA, ~10 Go) puis le modèle (~8 Go) : vérifier la place AVANT de télécharger
      need_space "$BIRD_HOME" 25 "vLLM et le modèle"
      say "Installation de vLLM (quelques minutes la première fois)…"
      rm -rf "$VLLM_VENV"  # un essai interrompu (disque plein, coupure) ne laisse jamais un environnement à moitié fait
      # uv fournit un Python que vLLM supporte (3.12), quel que soit celui du système (3.14…), et choisit la
      # version CUDA de torch adaptée à la carte ; sans cache : rien n'est téléchargé deux fois sur le disque
      export TMPDIR="$BIRD_HOME/tmp" UV_NO_CACHE=1 PIP_NO_CACHE_DIR=1
      mkdir -p "$TMPDIR"
      if "$VENV/bin/python" -m pip install -q uv >>"$LOGS/vllm-install.log" 2>&1 \
        && "$VENV/bin/uv" venv -q --python 3.12 "$VLLM_VENV" >>"$LOGS/vllm-install.log" 2>&1; then
        "$VENV/bin/uv" pip install -q --python "$VLLM_VENV/bin/python" --torch-backend=auto vllm huggingface_hub \
          >>"$LOGS/vllm-install.log" 2>&1 || install_failed
      else
        "$PY" -m venv "$VLLM_VENV" && "$VLLM_VENV/bin/python" -m pip install -q vllm huggingface_hub \
          >>"$LOGS/vllm-install.log" 2>&1 || install_failed
      fi
      rm -rf "$TMPDIR"
    fi
    # le modèle est sur Hugging Face : HF_TOKEN s'il est fourni, sinon la connexion « hf auth login »
    if [ -z "${HF_TOKEN:-}" ] && ! "$VLLM_VENV/bin/hf" auth whoami >/dev/null 2>&1; then
      if [ -r /dev/tty ]; then
        say "Connexion à Hugging Face (le modèle $BIRD_MODEL demande un compte autorisé) :"
        "$VLLM_VENV/bin/hf" auth login </dev/tty || die "Connexion à Hugging Face refusée."
      else
        die "Connectez-vous d'abord : $VLLM_VENV/bin/hf auth login (ou définissez HF_TOKEN)."
      fi
    fi
    # le téléchargement (~8 Go, une seule fois) avec sa propre barre de progression, avant le démarrage
    say "Téléchargement du modèle $BIRD_MODEL (une seule fois, ~8 Go)…"
    "$VLLM_VENV/bin/hf" download "$BIRD_MODEL" >/dev/null \
      || die "Téléchargement du modèle impossible : vérifiez votre connexion et votre accès au modèle (hf auth login)."
    # un démarrage précédent encore en cours (commande relancée, fenêtre fermée) : l'arrêter, jamais deux modèles
    # sur la même carte
    stop_previous_vllm
    # la mémoire vive : les poids (~8 Go) passent par elle pour aller sur la carte
    ram_mb="$(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null)"
    if [ -n "$ram_mb" ] && [ "$ram_mb" -lt 3000 ]; then
      if in_wsl; then
        say "Peu de mémoire vive disponible pour WSL ($((ram_mb / 1024)) Go) : le chargement sera lent. Fermez des applications Windows, ou donnez plus de mémoire à WSL (fichier %UserProfile%\\.wslconfig : [wsl2] memory=8GB, puis wsl --shutdown)."
      else
        say "Peu de mémoire vive disponible ($((ram_mb / 1024)) Go) : le chargement sera lent. Fermez des applications pour l'accélérer."
      fi
    fi
    say "Démarrage du modèle $BIRD_MODEL sur la carte graphique…"
    # HF_TOKEN, s'il est défini, est lu par vLLM depuis l'environnement : il n'est jamais écrit sur le disque ni affiché
    # shellcheck disable=SC2086  # VLLM_ARGS: words chosen above, never user input
    # --max-num-seqs 8 : une seule personne s'en sert ; moins de mémoire réservée et un démarrage plus court
    nohup "$VLLM_VENV/bin/vllm" serve "$BIRD_MODEL" --host 127.0.0.1 --port "$VLLM_PORT" --max-num-seqs 8 $VLLM_ARGS \
      >"$LOGS/vllm.log" 2>&1 &
    echo $! >"$BIRD_HOME/vllm.pid"
    wait_model
    ok "Modèle prêt sur $BASE_URL"
    # preuve que le modèle est bien sur la carte : sa mémoire est occupée par le serveur
    used="$("$NVSMI" --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -dc 0-9)"
    if [ -n "$used" ] && [ "$used" -gt 2000 ]; then
      ok "Accélération graphique active : $GPU_NAME, $((used / 1024)) Go occupés par le modèle"
    else
      say "Le modèle répond, mais la carte graphique ne semble pas utilisée : voir $LOGS/vllm.log"
    fi
  fi
fi
MODEL_ID="$(curl -fsS -m 5 "$BASE_URL/models" | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])')"
# un premier échange avec le modèle (API compatible OpenAI) : il répond avant que Bird ne démarre
REPLY="$(curl -fsS -m 120 -X POST "$BASE_URL/chat/completions" -H "Content-Type: application/json" \
  --data "{\"model\": \"$MODEL_ID\", \"max_tokens\": 20, \"messages\": [{\"role\": \"user\", \"content\": \"Dis bonjour en un mot.\"}]}" \
  | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"].strip()[:60])' 2>/dev/null)" \
  || die "Le modèle ne répond pas à une première question sur $BASE_URL/chat/completions."
ok "Le modèle $MODEL_ID répond : « $REPLY »"

# ---- 4. Bird, sur votre machine uniquement
cd "$APP"
if [ -f scripts/bird_local.py ]; then
  set -- "$VENV/bin/python" scripts/bird_local.py --vllm-url "$BASE_URL" --port "$BIRD_PORT" --no-browser
  # l'empreinte de chaque réponse mesurée sur votre carte (nvidia-smi), pas estimée
  [ -n "${GPU_NAME:-}" ] && set -- "$@" --measure-gpu
else
  set -- "$VENV/bin/python" scripts/serve.py --base-url "$BASE_URL" --model "$MODEL_ID" --api-key local \
    --host 127.0.0.1 --port "$BIRD_PORT"
fi
# un Bird local d'un essai précédent garde le port : l'arrêter d'abord
oldbird="$(cat "$BIRD_HOME/bird.pid" 2>/dev/null)"
if [ -n "$oldbird" ] && kill -0 "$oldbird" 2>/dev/null; then kill "$oldbird" 2>/dev/null; sleep 2; fi
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
# the page served by Bird local needs no code; the hosted chat gets a ready-made link (the code in its fragment)
LINK="$(sed -n 's/.*\(https:[^ ]*#bird-local=[0-9]*:[A-Z0-9-]*\).*/\1/p' "$LOGS/bird.log" 2>/dev/null | head -n 1)"
[ -n "$LINK" ] && echo "   Depuis bird-s.vercel.app, ouvrez : $LINK"
echo "   Journaux : $LOGS   ·   Arrêter : sh $BIRD_HOME/stop.sh"
echo "   Le modèle seul, en API compatible OpenAI :"
echo "     curl -X POST \"$BASE_URL/chat/completions\" -H \"Content-Type: application/json\" \\"
echo "       --data '{\"model\": \"$MODEL_ID\", \"messages\": [{\"role\": \"user\", \"content\": \"Bonjour\"}]}'"
if [ -n "${BIRD_NO_BROWSER:-}" ]; then :  # Windows (WSL) opens the page itself
elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
fi
