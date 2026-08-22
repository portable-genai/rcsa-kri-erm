"""The control-triad boundary: this repo keeps NO parallel control catalog (same as Aud2).

Rgc7 is the SINGLE SYSTEM OF RECORD for the obligation to policy to control to evidence graph. Erm1
CONSUMES the control library one-way and persists only RATINGS and ASSESSMENTS keyed on Rgc7's
control ids. This suite proves that boundary structurally, so it cannot erode into a parallel
catalog one convenient write method at a time:

* the only port onto controls is READ-ONLY: its Protocol exposes no mutating method;
* no registered port is a control-catalog STORE (a writable catalog by another name);
* the theme feed onto Aud3 is likewise read-only (Aud3 owns thematic RCA).
"""

from __future__ import annotations

from rcsa_kri_erm.ports import PORT_PROTOCOLS
from rcsa_kri_erm.ports.control_library import ControlLibraryPort
from rcsa_kri_erm.ports.theme_feed import ThemeFeedPort

#: Verbs that would make a read boundary a writable store. A method whose name starts with one of
#: these on the control-library or theme-feed port would be the first step to a parallel catalog.
_MUTATING_PREFIXES = (
    "write",
    "put",
    "create",
    "add",
    "insert",
    "update",
    "upsert",
    "delete",
    "remove",
    "store",
    "save",
    "persist",
    "set_",
    "register",
)


def _public_methods(protocol: type) -> list[str]:
    return [name for name in vars(protocol) if not name.startswith("_")]


def test_control_library_port_is_read_only() -> None:
    methods = _public_methods(ControlLibraryPort)
    assert set(methods) == {"list_controls", "get_control"}, (
        "the control-library port must stay read-only; a new method is how a parallel control "
        f"catalog begins. Found {sorted(methods)}"
    )
    for name in methods:
        assert not name.startswith(_MUTATING_PREFIXES), f"{name} looks like a write onto controls"


def test_theme_feed_port_is_read_only() -> None:
    methods = _public_methods(ThemeFeedPort)
    assert set(methods) == {"themes"}, "the Aud3 theme feed is one-way; it exposes no write path"


def test_no_registered_port_is_a_control_catalog_store() -> None:
    for port_name in PORT_PROTOCOLS:
        lowered = port_name.lower()
        is_catalog_store = ("control" in lowered) and any(
            token in lowered for token in ("catalog", "store", "inventory", "registry")
        )
        assert not is_catalog_store, (
            f"{port_name!r} names a control catalog store; Rgc7 owns the catalog and this repo "
            "keeps none of its own"
        )
