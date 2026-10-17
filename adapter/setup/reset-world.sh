#!/usr/bin/env bash
# Stops the server, puts adapter/server/world back to the pristine copy, and starts the server again in a detached
# screen session named mc. The world is only touched once the copy exists and the server process has exited.
set -euo pipefail

dir="$(cd "$(dirname "$0")/.." && pwd)/server"
cd "$dir"
[ -d world.pristine ] || { echo "no $dir/world.pristine to reset from" >&2; exit 1; }

running () { pgrep -f 'jar server.jar nogui' >/dev/null; }

if running; then
  screen -S mc -p 0 -X stuff $'stop\r'
  for _ in $(seq 120); do running || break; sleep 1; done
  if running; then
    echo "the server did not stop within 120 s; the world is unchanged" >&2
    exit 1
  fi
fi
# start.sh's cat outlives the server and keeps the old session open.
screen -S mc -X quit >/dev/null 2>&1 || true

rm -rf world
cp -R world.pristine world

started=$(date +%s)
screen -dmS mc ./start.sh
for _ in $(seq 180); do
  if [ "$(stat -f %m logs/latest.log 2>/dev/null || echo 0)" -ge "$started" ] && grep -q 'Done (' logs/latest.log; then
    echo "the server is up on a pristine world"
    exit 0
  fi
  sleep 1
done
echo "the server did not report Done within 180 s; see $dir/logs/latest.log" >&2
exit 1
