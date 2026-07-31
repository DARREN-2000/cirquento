"""Rule-set loading.

A RuleSet is the *versioned* regulatory logic. It is loaded once, pinned into
the run record, and never re-read mid-run — otherwise editing a YAML file
halfway through a batch would silently produce two different scoring regimes
inside one passport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

try:  # pyyaml is the normal path
    import yaml

    def _parse(text: str) -> dict[str, Any]:
        return yaml.safe_load(text)

except ModuleNotFoundError:  # pragma: no cover - tiny fallback parser
    def _parse(text: str) -> dict[str, Any]:
        raise RuntimeError("pyyaml is required to load rule sets")


class ScoreDimension(StrEnum):
    RECYCLED_CONTENT = "recycled_content"
    RECYCLABILITY = "recyclability"
    DISASSEMBLY = "disassembly"
    SUBSTANCES = "substances"


def _dec(value: Any) -> Decimal:
    # str() first: Decimal(0.3) is 0.29999... and scores must be exact.
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: str
    effective_from: str
    weights: Mapping[str, Decimal]
    joints: Mapping[str, Decimal]
    separability_floor: Decimal
    recyclability_map: Mapping[str, Decimal]
    substances_of_concern: frozenset[str]
    substance_penalty: Decimal
    data_quality: Mapping[str, Decimal] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "RuleSet":
        raw = _parse(Path(path).read_text(encoding="utf-8"))
        return cls(
            version=raw["version"],
            effective_from=str(raw.get("effective_from", "")),
            weights={k: _dec(v) for k, v in raw["weights"].items()},
            joints={k: _dec(v) for k, v in raw["joints"].items()},
            separability_floor=_dec(raw["separability_floor"]),
            recyclability_map={k: _dec(v) for k, v in raw["recyclability"].items()},
            substances_of_concern=frozenset(raw.get("substances_of_concern", ())),
            substance_penalty=_dec(raw.get("substance_penalty", 0)),
            data_quality={k: _dec(v) for k, v in raw.get("data_quality", {}).items()},
        )

    def weight(self, dimension: str) -> Decimal:
        return self.weights.get(dimension, Decimal(0))

    def joint_score(self, method: str) -> Decimal:
        """Unknown joints score 0, not the average.

        An unrecognised joining method is missing data, and missing data must
        never flatter a score — same principle as unknown recycled content.
        """
        return self.joints.get(method, Decimal(0))

    def recyclability(self, material_code: str | None) -> Decimal:
        if material_code is None:
            return Decimal(0)  # unclassified material is not creditable
        return self.recyclability_map.get(material_code, Decimal(0))

    def material_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.recyclability_map))
