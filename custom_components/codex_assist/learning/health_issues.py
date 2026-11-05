"""Observed, entry-specific repairs using the pinned HA 2026.10 issue API."""

from homeassistant.helpers import issue_registry as ir

from .. import DOMAIN

KINDS = ("bridge", "source", "entities", "pipeline", "launcher")
RESOLVED = {"verified", "available", "ready", "disabled", "not_required"}
UNKNOWN = {"not_checked", "checking"}


def issue_id(entry_id, kind):
    return f"voice_learning_{kind}_{entry_id}"


def observe(hass, entry, kind, status):
    """Unknown evidence preserves existing issues and their ignored state."""
    if kind not in KINDS or status in UNKNOWN:
        return
    key = issue_id(entry.entry_id, kind)
    if status in RESOLVED:
        ir.async_delete_issue(hass, DOMAIN, key)
        return
    # HA 2026.10 has no config_entry_id argument yet. Stable per-entry IDs and
    # data bind the repair; remove_entry explicitly cleans these known IDs only.
    ir.async_create_issue(
        hass,
        DOMAIN,
        key,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="voice_learning_" + kind,
        data={"entry_id": entry.entry_id, "kind": kind},
    )


def apply_report(hass, entry, report):
    for kind in KINDS:
        observe(hass, entry, kind, report[kind])


def remove_entry_issues(hass, entry):
    """Removal, not unload/reload, retires this entry's repairs."""
    for kind in KINDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry.entry_id, kind))
