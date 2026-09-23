"""Provider enablement shared by refresh, CLI, notifications, and API."""

from __future__ import annotations

from . import catalog, model

STARTER_SET = frozenset({"claude", "codex", "cursor"})


def family_default(family: str, detected: dict[str, bool],
                   table: catalog.Catalog) -> bool:
    provider = table.provider(family)
    if provider is None or family == "ollama":
        return False
    any_detected = any(detected.get(item.provider_id, False) and item.auto_enable
                       for item in table.providers)
    if any_detected:
        return bool(detected.get(family, False) and provider.auto_enable)
    return family in STARTER_SET


def enabled_card_ids(layout: dict | None, detected: dict[str, bool],
                     table: catalog.Catalog,
                     cards: list[model.CardRef]) -> set[str]:
    """Mirror Layout.defaults, firstRunComplete, and ensureCards."""
    saved = layout if isinstance(layout, dict) and layout.get("schema") == \
        "openusage-omarchy.layout.v1" else None
    slots = saved.get("cards") if saved else None
    slots = slots if isinstance(slots, dict) else {}
    first_run_done = bool(saved and saved.get("firstRunCompleted"))
    enabled: set[str] = set()
    for card in cards:
        if first_run_done:
            slot = slots.get(card.card_id)
            if not isinstance(slot, dict):
                slot = slots.get(card.family)
            value = slot.get("enabled") if isinstance(slot, dict) else None
            on = value if isinstance(value, bool) else bool(
                detected.get(card.family, False)
                and (table.provider(card.family) or _OFF).auto_enable)
        else:
            on = family_default(card.family, detected, table)
        if on:
            enabled.add(card.card_id)
    return enabled


def enabled_families(layout: dict | None, detected: dict[str, bool],
                     table: catalog.Catalog) -> set[str]:
    """Families worth discovering; disabled collectors stay untouched."""
    ids = [item.provider_id for item in table.providers]
    if isinstance(layout, dict) and isinstance(layout.get("cards"), dict):
        ids.extend(cid for cid in layout["cards"] if isinstance(cid, str))
    refs = [model.CardRef(cid, model.family_of(cid), cid) for cid in ids]
    return {model.family_of(cid) for cid in enabled_card_ids(
        layout, detected, table, refs)}


def detection_families(layout: dict | None,
                       table: catalog.Catalog) -> set[str]:
    """Probe credentials only for cards that can be enabled."""
    saved = layout if isinstance(layout, dict) and layout.get("schema") == \
        "openusage-omarchy.layout.v1" and layout.get("firstRunCompleted") else None
    slots = saved.get("cards") if saved and isinstance(saved.get("cards"), dict) else {}
    allowed = set()
    for provider in table.providers:
        if not provider.auto_enable:
            continue
        family = provider.provider_id
        slot = slots.get(family)
        if (not isinstance(slot, dict) or slot.get("enabled") is not False
                or any(model.family_of(cid) == family and isinstance(entry, dict)
                       and entry.get("enabled") is True
                       for cid, entry in slots.items() if isinstance(cid, str))):
            allowed.add(family)
    return allowed


class _Off:
    auto_enable = False


_OFF = _Off()
