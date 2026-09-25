#!/usr/bin/env bash
# THE verification entry point. Exits non-zero on any failure.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
for f in bin/* dev/*.sh tests/*.sh; do
  [ -e "$f" ] || continue
  bash -n "$f"
done
for f in tests/*.cjs; do
  [ -e "$f" ] || continue
  node "$f"
done
PYTHONPATH="$root/lib" python3 -B -m unittest discover -s tests -p '*_test.py'
if find . -path ./.git -prune -o -type d -name __pycache__ -print | grep -q .; then
  echo "tests/run.sh: __pycache__ found in tree" >&2
  find . -path ./.git -prune -o -type d -name __pycache__ -print >&2
  exit 1
fi
omarchy plugin validate .
