"""Closed material taxonomy.

This is the vocabulary the classifier is allowed to emit. It is a *closed* set
on purpose: the schema is generated from it, so an invented code fails
validation before it can reach a passport.

The enum is static (not generated at import time from YAML) because Pydantic
needs a concrete type, and because a taxonomy that can silently change shape
between deploys would break replay determinism.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Mapping


class TaxonomyCode(StrEnum):
    ALU_WROUGHT = "MET.ALU.WROUGHT"
    ALU_CAST = "MET.ALU.CAST"
    STEEL_CARBON = "MET.STEEL.CARBON"
    STEEL_STAINLESS = "MET.STEEL.STAINLESS"
    CU_WIRE = "MET.CU.WIRE"
    PA66_GF30 = "POL.PA66.GF30"
    PP_TALC = "POL.PP.TALC"
    ABS = "POL.ABS"
    PC_ABS = "POL.PC.ABS"
    EPOXY = "THERMOSET.EPOXY"
    PCBA = "ELEC.PCBA"
    SEMI = "ELEC.SEMI"
    CFRP = "COMPOSITE.CFRP"


# Deterministic aliases. Anything matched here never reaches the model:
# it is cheaper, exact, and a known code should not be re-litigated by a
# probabilistic system.
DEFAULT_ALIASES: Mapping[str, TaxonomyCode] = {
    "alu extr": TaxonomyCode.ALU_WROUGHT,
    "aluminium extrusion": TaxonomyCode.ALU_WROUGHT,
    "aluminum extrusion": TaxonomyCode.ALU_WROUGHT,
    "en aw-6060": TaxonomyCode.ALU_WROUGHT,
    "en aw-6082": TaxonomyCode.ALU_WROUGHT,
    "aldc12": TaxonomyCode.ALU_CAST,
    "die cast aluminium": TaxonomyCode.ALU_CAST,
    "s235jr": TaxonomyCode.STEEL_CARBON,
    "dc01": TaxonomyCode.STEEL_CARBON,
    "1.4301": TaxonomyCode.STEEL_STAINLESS,
    "aisi 304": TaxonomyCode.STEEL_STAINLESS,
    "cu-etp": TaxonomyCode.CU_WIRE,
    "copper wire": TaxonomyCode.CU_WIRE,
    "pa66-gf30": TaxonomyCode.PA66_GF30,
    "pa66 gf30": TaxonomyCode.PA66_GF30,
    "pp-t20": TaxonomyCode.PP_TALC,
    "pc/abs": TaxonomyCode.PC_ABS,
    "epoxy potting": TaxonomyCode.EPOXY,
    "pcb assembly": TaxonomyCode.PCBA,
    "pcba": TaxonomyCode.PCBA,
}

LABELS: Mapping[TaxonomyCode, str] = {
    TaxonomyCode.ALU_WROUGHT: "Wrought aluminium (extrusion, sheet)",
    TaxonomyCode.ALU_CAST: "Cast aluminium (die/gravity cast)",
    TaxonomyCode.STEEL_CARBON: "Carbon steel",
    TaxonomyCode.STEEL_STAINLESS: "Stainless steel",
    TaxonomyCode.CU_WIRE: "Copper conductor / wire",
    TaxonomyCode.PA66_GF30: "Polyamide 66, 30% glass filled",
    TaxonomyCode.PP_TALC: "Polypropylene, talc filled",
    TaxonomyCode.ABS: "ABS",
    TaxonomyCode.PC_ABS: "PC/ABS blend",
    TaxonomyCode.EPOXY: "Thermoset epoxy (potting, adhesive)",
    TaxonomyCode.PCBA: "Populated printed circuit board",
    TaxonomyCode.SEMI: "Semiconductor device",
    TaxonomyCode.CFRP: "Carbon fibre reinforced polymer",
}

_WS = re.compile(r"\s+")


class Taxonomy:
    def __init__(self, aliases: Mapping[str, TaxonomyCode] | None = None) -> None:
        self._aliases = dict(aliases or DEFAULT_ALIASES)

    @staticmethod
    def normalize(text: str) -> str:
        return _WS.sub(" ", text.lower()).strip()

    def exact_match(self, description: str) -> TaxonomyCode | None:
        """Deterministic pre-pass.

        Matches the code itself, or a known alias appearing as a substring.
        Longest alias first, so "pa66 gf30" never loses to a shorter prefix.
        """
        norm = self.normalize(description)
        for code in TaxonomyCode:
            if code.value.lower() == norm:
                return code
        for alias in sorted(self._aliases, key=len, reverse=True):
            if alias in norm:
                return self._aliases[alias]
        return None

    def render_for_prompt(self) -> str:
        return "\n".join(f"- {c.value}: {LABELS[c]}" for c in TaxonomyCode)

    def __contains__(self, code: object) -> bool:
        return code in set(TaxonomyCode)
