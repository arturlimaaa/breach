#!/bin/sh
# Install rmalde/minecraft-agent, system B on Minecraft, into third_party/rmalde at the commit B was read from.
# The repository has no license, so none of its code enters ours: it stays in that gitignored folder and runs there.
set -eu
cd "$(dirname "$0")/../.."
COMMIT=78b40ed59514e5e2abde33a05ce398ecb2c39e05
DIR=third_party/rmalde
[ -d "$DIR/.git" ] || git clone --quiet https://github.com/rmalde/minecraft-agent.git "$DIR"
git -C "$DIR" checkout --quiet --detach "$COMMIT"
# npm ci installs his lockfile's versions and runs his postinstall, which patches mineflayer-pathfinder and the viewer.
cd "$DIR"
npm ci --no-audit --no-fund
