#!/usr/bin/env bash
# Regenerate the architecture diagram renders from architecture.dot.
# Requires Graphviz (e.g. `sudo apt-get install -y graphviz fonts-dejavu`).
set -euo pipefail
cd "$(dirname "$0")"
dot -Tpng -Gdpi=110 architecture.dot -o architecture.png
dot -Tsvg architecture.dot -o architecture.svg
echo "rendered architecture.png and architecture.svg"
