#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Dev loop: copy the workspace into the installed plugin, validate, and
# restart the shell. The shell's hot reload keeps serving stale nested QML
# (e.g. qml/UsageTrend.qml loaded via MetricRow), so the restart is required.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
dest="$HOME/.config/omarchy/plugins/luth-v.openusage-omarchy"
rsync -a --delete --exclude .git --exclude __pycache__ "$root/" "$dest/"
omarchy plugin validate "$dest"
omarchy-restart-shell
