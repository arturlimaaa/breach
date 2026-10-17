#!/usr/bin/env bash
# Prepares adapter/server/ for a local vanilla 1.16.5 server. Skips the download when server.jar already matches.
# Installing a JDK and accepting the Minecraft EULA are the operator's acts; this script does neither.
set -euo pipefail

sha=1b557e7b033b583cd9f66746b7a9ab1ec1673ced
url="https://launcher.mojang.com/v1/objects/$sha/server.jar"
dir="$(cd "$(dirname "$0")/.." && pwd)/server"
user="${MC_USERNAME:-breach}"

sha1 () { shasum -a 1 "$1" | cut -d ' ' -f 1; }

mkdir -p "$dir"
cd "$dir"

if [ -f server.jar ] && [ "$(sha1 server.jar)" = "$sha" ]; then
  echo "server.jar is already 1.16.5 (SHA-1 $sha), not downloading"
else
  curl -fL --retry 2 -o server.jar.part "$url"
  if [ "$(sha1 server.jar.part)" != "$sha" ]; then
    rm -f server.jar.part
    echo "downloaded server.jar does not match SHA-1 $sha" >&2
    exit 1
  fi
  mv server.jar.part server.jar
fi

cat > server.properties <<EOF
difficulty=peaceful
spawn-protection=0
view-distance=10
level-seed=${MC_SEED:-}
online-mode=false
server-port=25565
EOF

# The adapter's reset runs /clear and /give, which need op level 2. Offline mode keys players by this name-derived
# UUID, while `op <name>` may resolve a Mojang account of the same name.
if [ ! -f ops.json ]; then
  h=$(printf 'OfflinePlayer:%s' "$user" | md5)
  uuid=$(printf '%s-%s-3%s-%x%s-%s' "${h:0:8}" "${h:8:4}" "${h:13:3}" $(( (0x${h:16:1} & 3) | 8 )) "${h:17:3}" "${h:20:12}")
  printf '[{"uuid": "%s", "name": "%s", "level": 2, "bypassesPlayerLimit": false}]\n' "$uuid" "$user" > ops.json
fi

cat > start.sh <<'EOF'
#!/bin/sh
# The server queues these commands and runs them once the world has loaded; type further commands here.
# A console command runs at the world spawn, so `~ ~` centers the border there.
cd "$(dirname "$0")"
{
  printf '%s\n' 'gamerule doDaylightCycle false' 'gamerule keepInventory true' \
    'worldborder center ~ ~' 'worldborder set 256' 'difficulty peaceful'
  cat
} | java -Xmx2G -jar server.jar nogui
EOF
chmod +x start.sh

cat <<EOF

Server files are in $dir
Two steps are the operator's, and this script did neither:
  1. Install a JDK and put it on PATH:
       brew install openjdk@17
       export PATH="\$(brew --prefix openjdk@17)/bin:\$PATH"
  2. Read the Minecraft EULA (https://aka.ms/MinecraftEULA). To accept it, put eula=true in
       $dir/eula.txt
Then run $dir/start.sh, and npm start in adapter/ once the server says Done.
EOF
