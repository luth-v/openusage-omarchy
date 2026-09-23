"""Package entry point. Never writes bytecode inside the plugin tree."""

import os
import sys

sys.dont_write_bytecode = True
_here = os.path.dirname(os.path.abspath(__file__))
if sys.path and sys.path[0] == _here:
    # Script mode puts the package dir first; drop it so our http.py
    # cannot shadow the stdlib http package urllib needs.
    sys.path.pop(0)
sys.path.insert(0, os.path.dirname(_here))

from openusage_omarchy.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
