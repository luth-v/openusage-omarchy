"""Pricing store. Bundled snapshots plus hourly refetch."""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from .. import atomic, catalog as _catalog, log
from . import price_catalog as _codecs
from .pricing import EMPTY, ModelPricing
from .supplement import Supplement

LITELLM_URL = ("https://raw.githubusercontent.com/BerriAI/litellm/main/"
               "model_prices_and_context_window.json")
MODELS_DEV_URL = "https://models.dev/api.json"
SUPPLEMENT_URL = "https://robinebers.github.io/openusage/pricing_supplement.json"
REFRESH_S = 3600
RETRY_S = 1800


def _bundled(name: str) -> bytes | None:
    try:
        return (_catalog.plugin_root() / "data" / f"{name}.json").read_bytes()
    except OSError:
        return None


class Store:
    """Stale-while-revalidate pricing with ETag and state file.

    ``current()`` never blocks on the network: it serves the bundled plus
    cached data on hand and revalidates in a background thread, as upstream
    ``ModelPricingStore.current()``. One refresh runs per cache dir at a
    time; every caller shares the files it writes.
    """

    _guard = threading.Lock()
    _inflight: dict[str, threading.Thread] = {}

    def __init__(self, cache_dir: Path, http: Any = None,
                 urls: dict[str, str] | None = None) -> None:
        self.cache_dir = cache_dir
        self.http = http
        self.urls = urls or {"litellm": LITELLM_URL,
                             "models_dev": MODELS_DEV_URL,
                             "supplement": SUPPLEMENT_URL}
        self._pricing: ModelPricing = EMPTY
        self._states: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._log = log.get_logger("pricing")

    def current(self) -> ModelPricing:
        if not self._loaded:
            self._load()
        self.refresh_due_background()
        return self._pricing

    def refresh_due_background(self) -> bool:
        """Kick a refresh thread when a source is due. Never blocks."""
        if self.http is None:
            return False
        key = str(self.cache_dir)
        with Store._guard:
            live = Store._inflight.get(key)
            if live is not None and live.is_alive():
                return True
            worker = threading.Thread(
                target=self._background, name="openusage-pricing",
                daemon=True)
            Store._inflight[key] = worker
            worker.start()
            return True

    def _background(self) -> None:
        try:
            self.refresh_due()
        except Exception:
            pass
        finally:
            key = str(self.cache_dir)
            with Store._guard:
                if Store._inflight.get(key) is threading.current_thread():
                    Store._inflight.pop(key, None)

    def refresh_now(self, now: dt.datetime | None = None,
                    timeout: float = 120) -> bool:
        """Deterministic refresh point for tests and the CLI.

        Joins an in-flight background refresh first so back-to-back calls
        cannot overlap on one cache dir, then runs due fetches inline.
        """
        key = str(self.cache_dir)
        with Store._guard:
            live = Store._inflight.get(key)
        if live is not None and live is not threading.current_thread():
            live.join(timeout=timeout)
        if not self._loaded:
            self._load()
        return self.refresh_due(now=now)

    @classmethod
    def join_background(cls, timeout: float = 30) -> None:
        """Join every in-flight refresh thread. Tests call this on teardown
        so no worker outlives its temporary cache dir."""
        with cls._guard:
            threads = [thread for thread in cls._inflight.values()
                       if thread is not threading.current_thread()]
        for thread in threads:
            thread.join(timeout=timeout)

    def source_info(self) -> tuple[str, str | None]:
        if not self._loaded:
            self._load()
        stamped = [self._states.get(name, {}).get("fetchedAt")
                   for name in ("litellm", "models_dev", "supplement")]
        dated = sorted(item for item in stamped if isinstance(item, str))
        if dated:
            return "litellm", dated[-1]
        for name, loader in (
                ("pricing_litellm_snapshot", _codecs.catalog_from_compact),
                ("pricing_models_dev_snapshot", _codecs.catalog_from_compact),
                ("pricing_supplement", Supplement.decode)):
            raw = _bundled(name)
            if raw is None:
                continue
            try:
                loader(raw)
                return "bundled", None
            except (ValueError, KeyError):
                continue
        return "bundled", None

    def _load(self) -> None:
        self._loaded = True
        raw = atomic.read_json(self.cache_dir / "state.json")
        self._states = raw if isinstance(raw, dict) else {}
        self._pricing = ModelPricing(
            self._load_supplement(),
            self._load_catalog("litellm", "pricing_litellm_snapshot"),
            self._load_catalog("models_dev", "pricing_models_dev_snapshot"))

    def _write_states(self) -> None:
        try:
            atomic.write_json_atomic(self.cache_dir / "state.json", self._states)
        except OSError as exc:
            self._log.warning("pricing state write failed: %s", exc)

    def _load_supplement(self) -> Supplement:
        cached = None
        raw = atomic.read_json(self.cache_dir / "supplement.json")
        if raw is not None:
            try:
                cached = Supplement.decode(json.dumps(raw).encode())
            except (ValueError, KeyError):
                self._log.warning("cached supplement unreadable, using bundled")
        bundled = None
        data = _bundled("pricing_supplement")
        if data is not None:
            try:
                bundled = Supplement.decode(data)
            except (ValueError, KeyError):
                self._log.error("bundled pricing_supplement.json unreadable")
        else:
            self._log.error("bundled pricing_supplement.json missing")
        if cached is not None and bundled is not None:
            newer = (bundled.updated_at or "") > (cached.updated_at or "")
            picked = bundled if newer and bundled.updated_at else cached
            if not cached.updated_at and bundled.updated_at:
                picked = bundled
            return picked.filling_missing_fallbacks(bundled)
        return cached or bundled or Supplement()

    def _load_catalog(self, source: str, bundled_name: str) -> _codecs.PricingCatalog:
        catalog = _codecs.PricingCatalog()
        data = _bundled(bundled_name)
        if data is not None:
            try:
                catalog = _codecs.catalog_from_compact(data)
            except ValueError:
                self._log.error("bundled %s.json unreadable", bundled_name)
        else:
            self._log.error("bundled %s.json missing", bundled_name)
        cached = self.cache_dir / f"{source}.json"
        if cached.is_file():
            try:
                catalog = catalog.merging(_codecs.catalog_from_compact(cached.read_bytes()))
            except (OSError, ValueError):
                self._log.warning("cached %s catalog unreadable, using bundled", source)
        return catalog

    def _due(self, source: str, now: dt.datetime) -> bool:
        state = self._states.get(source) or {}
        failed = state.get("failedAt")
        if isinstance(failed, str):
            try:
                if (now - dt.datetime.fromisoformat(failed)).total_seconds() < RETRY_S:
                    return False
            except ValueError:
                pass
        fetched = state.get("fetchedAt")
        if not isinstance(fetched, str):
            return True
        try:
            return (now - dt.datetime.fromisoformat(fetched)).total_seconds() >= REFRESH_S
        except ValueError:
            return True

    def refresh_due(self, now: dt.datetime | None = None) -> bool:
        if self.http is None:
            return False
        moment = now or dt.datetime.now(dt.timezone.utc)
        changed = False
        for source in ("litellm", "models_dev", "supplement"):
            if self._due(source, moment) and self._fetch(source, moment):
                changed = True
        if changed:
            kept = dict(self._states)
            self._load()
            self._states.update(kept)
            self._log.info(
                "pricing refreshed (%d LiteLLM, %d models.dev, %d supplement)",
                len(self._pricing.primary.entries),
                len(self._pricing.secondary.entries),
                len(self._pricing.supplement.pricing))
        self._write_states()
        return changed

    def _fetch(self, source: str, now: dt.datetime) -> bool:
        url = self.urls.get(source)
        if not url:
            return False
        state = dict(self._states.get(source) or {})
        headers: dict[str, str] = {}
        if state.get("etag"):
            headers["If-None-Match"] = str(state["etag"])
        try:
            reply = self.http.get(url, headers=headers or None, timeout=30)
        except Exception as exc:
            state["failedAt"] = now.isoformat()
            self._states[source] = state
            self._log.warning("%s refresh failed: %s", source, type(exc).__name__)
            return False
        status = getattr(reply, "status", 0)
        if status == 304:
            state["fetchedAt"] = now.isoformat()
            state.pop("failedAt", None)
            self._states[source] = state
            return False
        if status != 200:
            state["failedAt"] = now.isoformat()
            self._states[source] = state
            self._log.warning("%s refresh failed: HTTP %s", source, status)
            return False
        body = bytes(getattr(reply, "body", b""))
        try:
            if source == "litellm":
                payload = _codecs.compact_data(_codecs.catalog_from_litellm(body))
            elif source == "models_dev":
                payload = _codecs.compact_data(_codecs.catalog_from_modelsdev(body))
            else:
                Supplement.decode(body)
                payload = body
        except (ValueError, KeyError):
            state["failedAt"] = now.isoformat()
            self._states[source] = state
            self._log.warning("%s refresh failed: bad payload", source)
            return False
        try:
            target = self.cache_dir / f"{source}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except OSError:
            state["failedAt"] = now.isoformat()
            self._states[source] = state
            return False
        header = getattr(reply, "header", None)
        etag = header("etag") if callable(header) else None
        if etag:
            state["etag"] = etag
        state["fetchedAt"] = now.isoformat()
        state.pop("failedAt", None)
        self._states[source] = state
        return True
