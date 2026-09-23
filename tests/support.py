"""Shared test fakes. Not a test module (discover pattern is *_test.py)."""

from __future__ import annotations

import datetime as dt
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from openusage_omarchy import http as _http, paths
from openusage_omarchy.providers import Env

NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.timezone.utc)


class FakeClock:
    def __init__(self, now: dt.datetime = NOW) -> None:
        self.value = now

    def now(self) -> dt.datetime:
        return self.value


class FakeHttp:
    """Route table keyed by (method, url). Values are (status, body, headers)."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, bytes, dict[str, str] | None]] = {}
        self.calls: list[tuple[str, str]] = []

    def add(
        self,
        method: str,
        url: str,
        status: int,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes[(method, url)] = (status, body, headers)

    def add_json(
        self,
        method: str,
        url: str,
        payload: object,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        import json

        self.add(method, url, status, json.dumps(payload).encode(), headers)

    def _serve(self, method: str, url: str) -> _http.Response:
        self.calls.append((method, url))
        if (method, url) not in self.routes:
            raise _http.HttpError(f"{method} {url} failed: not stubbed")
        status, body, headers = self.routes[(method, url)]
        if status >= 500:
            raise _http.HttpError(f"{method} {url} returned status {status}", status)
        return _http.Response(status=status, body=body, headers=headers)

    def get(self, url: str, headers: dict | None = None, timeout: float = 10) -> _http.Response:
        return self._serve("GET", url)

    def post(
        self, url: str, body: bytes, headers: dict | None = None, timeout: float = 10
    ) -> _http.Response:
        return self._serve("POST", url)


@contextmanager
def test_env(tmp: str | os.PathLike[str], now: dt.datetime = NOW) -> Iterator[Env]:
    base = Path(tmp)
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "HOME": str(base / "home"),
        "XDG_STATE_HOME": str(base / "state"),
        "XDG_CACHE_HOME": str(base / "cache"),
        "XDG_CONFIG_HOME": str(base / "config"),
        "XDG_DATA_HOME": str(base / "data"),
        "XDG_RUNTIME_DIR": str(base / "run"),
        "GROK_HOME": str(base / "home" / ".grok"),
        "OPENCODE_DATA_DIR": "",
        # An empty PATH hides the real secret-tool so keyring reads cannot
        # leak the developer's logins into tests. Tests that need a keyring
        # prepend their own shim dir to PATH inside this context.
        "PATH": str(bin_dir),
    }
    with patch.dict(os.environ, mapping, clear=False):
        os.environ.pop("OPENCODE_DATA_DIR", None)
        for name in (
            "OPENROUTER_API_KEY", "OPENROUTER_KEY", "ZAI_API_KEY", "GLM_API_KEY",
        ):
            os.environ.pop(name, None)
        logger = logging.getLogger("openusage_omarchy")
        mute = logging.NullHandler()
        logger.addHandler(mute)
        try:
            yield Env(http=FakeHttp(), clock=FakeClock(now), paths=paths.Paths.from_env())
        finally:
            logger.removeHandler(mute)


SHIM_SOURCE = '''#!{python}
"""Fake secret-tool. Lookup hits and store exits are driven by env vars."""
import os
import sys

with open(os.environ["SHIM_LOG"], "a") as handle:
    handle.write("argv=" + repr(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
cmd = args[0] if args else ""
pairs = dict(zip(args[1::2], args[2::2]))
if cmd == "lookup":
    if pairs.get("provider") == "openrouter" and os.environ.get("SHIM_HIT_OPENROUTER"):
        print("test-only-shim-openrouter")
    elif pairs.get("provider") == "zai" and os.environ.get("SHIM_HIT_ZAI"):
        print("test-only-shim-zai")
    elif pairs.get("service") == "gh:github.com" and os.environ.get("SHIM_HIT_GH"):
        print(os.environ["SHIM_HIT_GH"])
    elif pairs.get("service") == "gemini" and os.environ.get("SHIM_HIT_GEMINI"):
        print(os.environ["SHIM_HIT_GEMINI"])
    else:
        sys.exit(1)
elif cmd == "store":
    body = sys.stdin.buffer.read()
    with open(os.environ["SHIM_LOG"], "a") as handle:
        handle.write(f"store_stdin_len={len(body)}\\n")
    sys.exit(int(os.environ.get("SHIM_STORE_EXIT", "0")))
elif cmd == "clear":
    pass
else:
    sys.exit(1)
'''


def install_shim(base: Path) -> Path:
    """Write the fake secret-tool into base/shim and return that dir."""
    import sys

    shim_dir = base / "shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    tool = shim_dir / "secret-tool"
    tool.write_text(SHIM_SOURCE.replace("{python}", sys.executable), encoding="utf-8")
    tool.chmod(0o755)
    (base / "shim.log").write_text("", encoding="utf-8")
    return shim_dir
