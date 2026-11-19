#!/usr/bin/env bash
# Bot commit'ин жоготпой push кылуу: башка процесс ошол эле branch'ка push кылса — rebase, 4 аракет.
# Колдонуу: bash commit_push.sh "<билдирүү>" <жол>...
set -uo pipefail
msg="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A "$@"
if git diff --cached --quiet; then echo "өзгөрүү жок"; exit 0; fi
git commit -q -m "$msg"
branch=$(git rev-parse --abbrev-ref HEAD)
for i in 1 2 3 4; do
  if git push -q origin "HEAD:$branch"; then echo "push ✅ ($i-аракет)"; exit 0; fi
  echo "push четке кагылды ($i) — алыскы өзгөртүүлөрдү алып, кайра аракет"
  sleep $((i * 3))
  git pull -q --rebase origin "$branch" || { echo "::error::rebase болбоду"; git rebase --abort 2>/dev/null; exit 1; }
done
echo "::error::push 4 аракеттен кийин да болбоду — натыйжа artifact'та гана"; exit 1
