#!/bin/sh
# Builds dist/doricomcp.mcpb (a Claude Desktop extension) from the published files only.
set -eu
cd "$(dirname "$0")/.."
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp manifest.json icon.png pyproject.toml uv.lock README.md LICENSE "$stage"
git ls-files -co --exclude-standard doricomcp | rsync -a --files-from=- . "$stage"
mkdir -p dist
npx -y @anthropic-ai/mcpb@2.1.2 validate "$stage/manifest.json"
npx -y @anthropic-ai/mcpb@2.1.2 pack "$stage" dist/doricomcp.mcpb
