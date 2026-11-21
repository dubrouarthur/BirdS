#!/usr/bin/env bash
# Publish a merged checkpoint stored in a bucket to a model repo, one file at a time
# (bucket -> repo copies are not supported server-side; local disk is limited).
# Files already in the repo are skipped. With DELETE_AFTER=1, each file is removed from the bucket
# only AFTER it was uploaded successfully (keeps private storage usage flat).
# Usage: [DELETE_AFTER=1] scripts/publish_from_bucket.sh adubrou/birds-runs bird-v0/merged adubrou/Bird-S-4B out/model_card/README.md
set -euo pipefail
BUCKET="$1"; PREFIX="$2"; REPO="$3"; CARD="$4"
TMP="${TMPDIR:-/tmp}/bird_publish"
mkdir -p "$TMP"
existing=$(python3 -c "from huggingface_hub import list_repo_files; print('\n'.join(list_repo_files('$REPO')))" 2>/dev/null || true)
files=$(hf buckets ls "$BUCKET" -R 2>/dev/null | awk -v p="$PREFIX/" 'index($NF, p) == 1 {print $NF}' | grep -v '/\.tmp' || true)
[ -n "$files" ] || { echo "no files under $BUCKET/$PREFIX" >&2; exit 1; }
for f in $files; do
  name="${f#"$PREFIX"/}"
  if ! grep -qxF "$name" <<<"$existing"; then
    hf buckets cp "hf://buckets/$BUCKET/$f" "$TMP/$name" >/dev/null
    hf upload "$REPO" "$TMP/$name" "$name" --commit-message "Bird: add $name" >/dev/null
    rm -f "$TMP/$name"
    echo "published $name"
  else
    echo "already published $name"
  fi
  if [ "${DELETE_AFTER:-0}" = "1" ]; then
    hf buckets rm "$BUCKET/$f" --yes >/dev/null && echo "removed from bucket $name"
  fi
done
hf upload "$REPO" "$CARD" README.md --commit-message "Bird: model card" >/dev/null
echo "published README.md"
