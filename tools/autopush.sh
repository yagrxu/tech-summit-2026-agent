#!/bin/bash
# Auto-commit & push the workspace every ~3 minutes. Launched detached; stop with: kill $(cat .autopush.pid)
cd "$(dirname "$0")/.." || exit 1
while true; do
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git -c user.name="yagrxu" -c user.email="yagrxu@users.noreply.github.com" \
        commit -q -m "auto: progress snapshot $(date '+%Y-%m-%d %H:%M')" && git push -q origin HEAD 2>/dev/null \
        || git push -q origin HEAD 2>/dev/null
    echo "$(date '+%H:%M:%S') pushed" >> .autopush.log
  else
    echo "$(date '+%H:%M:%S') no changes" >> .autopush.log
  fi
  sleep 180
done
