#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT_DIR/mac-app/build_app.sh"
open "$ROOT_DIR/dist/NiimbotPopup.app"
