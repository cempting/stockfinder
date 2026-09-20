"""Shared top-down selection context for linked dashboard widgets."""

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

CONTEXT_KEYS = ("region", "sector", "industry", "instrument")


@dataclass
class AnalysisContext:
    """Read and update hierarchical selections backed by session state."""

    state: MutableMapping[str, Any]
    prefix: str = "analysis_context"

    def get(self, level: str) -> str | None:
        self._validate_level(level)
        value = self.state.get(self._key(level))
        return str(value) if value else None

    def select(self, level: str, value: str | None) -> None:
        """Select one level and clear selections below it."""
        self._validate_level(level)
        index = CONTEXT_KEYS.index(level)
        key = self._key(level)
        if value:
            self.state[key] = value
        else:
            self.state.pop(key, None)
        for descendant in CONTEXT_KEYS[index + 1 :]:
            self.state.pop(self._key(descendant), None)

    def snapshot(self) -> dict[str, str]:
        return {
            level: value
            for level in CONTEXT_KEYS
            if (value := self.get(level)) is not None
        }

    def breadcrumb(self) -> tuple[str, ...]:
        return tuple(self.snapshot().values())

    def _key(self, level: str) -> str:
        return f"{self.prefix}_{level}"

    @staticmethod
    def _validate_level(level: str) -> None:
        if level not in CONTEXT_KEYS:
            raise ValueError(f"Unknown analysis context level: {level}")