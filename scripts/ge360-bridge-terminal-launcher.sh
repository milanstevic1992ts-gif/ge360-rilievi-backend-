#!/usr/bin/env bash
set -euo pipefail

CMD="sudo -E /usr/local/sbin/ge360-bridge-wizard"

hold='echo; echo "Premi Invio per chiudere..."; read -r _'
payload="$CMD; rc=\$?; echo; echo \"GE360 Bridge setup terminato (codice \$rc)\"; $hold; exit \$rc"

if command -v x-terminal-emulator >/dev/null 2>&1; then
  exec x-terminal-emulator -e bash -lc "$payload"
elif command -v gnome-terminal >/dev/null 2>&1; then
  exec gnome-terminal -- bash -lc "$payload"
elif command -v konsole >/dev/null 2>&1; then
  exec konsole -e bash -lc "$payload"
elif command -v xfce4-terminal >/dev/null 2>&1; then
  exec xfce4-terminal --command="bash -lc '$payload'"
else
  exec bash -lc "$payload"
fi
