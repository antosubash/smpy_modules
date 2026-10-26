"""The bundle sections other modules registered on this app (#80).

Lives on ``app.state.pagebuilder.bundle_sections``, created with the services
container in ``register_settings`` — during app construction, before any
module's ``on_startup`` — so a contributor can register whichever order the
host starts modules in. Read-only once the first request is served.

The public way in is :func:`pagebuilder.contracts.bundle.register_section`;
this is the store behind it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING

from pagebuilder.snapshots.manifest import RESERVED_SECTION_NAMES, SECTION_NAME

if TYPE_CHECKING:
    from pagebuilder.contracts.bundle import BundleSection


class SectionRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, BundleSection] = {}

    def register(self, section: BundleSection) -> None:
        name = getattr(section, "name", None)
        if not isinstance(name, str) or not SECTION_NAME.match(name):
            raise ValueError(f"bundle section name {name!r} is not [a-z][a-z0-9_]*")
        if name in RESERVED_SECTION_NAMES:
            raise ValueError(f"bundle section name {name!r} is reserved for pagebuilder")
        if name in self._sections:
            raise ValueError(f"bundle section {name!r} is already registered")
        version = section.version
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError(f"bundle section {name!r} has no integer version")
        if version not in section.readable_versions:
            raise ValueError(f"bundle section {name!r} cannot read the version {version} it writes")
        if not isinstance(section.required, bool):
            raise ValueError(f"bundle section {name!r} has a non-boolean 'required'")
        if not isinstance(getattr(section, "label_key", None), str):
            raise ValueError(f"bundle section {name!r} has no label_key")
        keys = getattr(section, "count_label_keys", None)
        if not isinstance(keys, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in keys.items()
        ):
            raise ValueError(f"bundle section {name!r} needs count_label_keys: {{kind: key}}")
        for stage in ("capture", "apply"):
            perms = getattr(section, f"{stage}_permissions", frozenset())
            if (
                isinstance(perms, str)
                or not isinstance(perms, Iterable)
                or not all(isinstance(p, str) and p for p in perms)
            ):
                raise ValueError(
                    f"bundle section {name!r} needs {stage}_permissions as a set of names"
                )
        for method in ("capture", "validate", "plan", "apply"):
            if not callable(getattr(section, method, None)):
                raise ValueError(f"bundle section {name!r} has no {method}() method")
        self._sections[name] = section

    def get(self, name: str) -> BundleSection | None:
        return self._sections.get(name)

    def __iter__(self) -> Iterator[BundleSection]:
        """Every section, in name order — the order they capture and apply in."""
        return iter(self._sections[name] for name in sorted(self._sections))

    def __len__(self) -> int:
        return len(self._sections)

    def labels(self) -> list[dict[str, object]]:
        """How the screens name each section: its catalogue keys, in name order."""
        return [
            {
                "section": section.name,
                "label_key": section.label_key,
                "count_label_keys": dict(section.count_label_keys),
            }
            for section in self
        ]

    def readable(self) -> dict[str, frozenset[int]]:
        """``{section: readable versions}``, for the manifest check."""
        return {name: frozenset(s.readable_versions) for name, s in self._sections.items()}
