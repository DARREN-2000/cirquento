"""Tamper-evident seals over a passport's content hash.

**What this is and is not.** This is an HMAC-SHA256 seal with a shared secret.
It proves a passport was not altered *between two systems that both hold the
key* — an ERP pushing to an auditor's intake, an export replayed from cold
storage. It does **not** let an arbitrary third party verify authorship,
because anyone who can verify can also forge. That requires asymmetric signing
(Ed25519 / X.509), which is on the roadmap and deliberately not faked here.

Claiming "signed passports" while shipping an HMAC would be the kind of
overstatement this project exists to avoid, so the algorithm is named in the
seal itself and the verifier refuses anything it does not recognise.

The seal is taken over the **content hash**, not the serialised document, so it
survives re-serialisation, key reordering and envelope metadata like
`issuedAt` — the same property that makes replays byte-identical.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

ALGORITHM = "HMAC-SHA256"
ENV_KEY = "CIRQUENTO_SEAL_KEY"


class SealError(RuntimeError):
    """Raised when a seal cannot be produced or is not valid."""


@dataclass(frozen=True, slots=True)
class Seal:
    algorithm: str
    key_id: str
    content_hash: str
    signature: str

    def as_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "keyId": self.key_id,
            "contentHash": self.content_hash,
            "signature": self.signature,
        }


def _key_material(key: str | None) -> bytes:
    material = key if key is not None else os.environ.get(ENV_KEY)
    if not material:
        raise SealError(
            f"No sealing key. Set {ENV_KEY} or pass one explicitly. "
            "Refusing to fall back to a default key, because a well-known key "
            "produces seals that look valid and prove nothing."
        )
    return material.encode("utf-8")


def key_id(key: str | None = None) -> str:
    """A stable, non-reversible identifier for the key in use.

    Lets a verifier say "sealed with a key I don't have" instead of the far less
    useful "invalid", and never puts the secret itself in the artefact.
    """
    digest = hashlib.sha256(_key_material(key)).hexdigest()
    return f"sha256:{digest[:16]}"


def seal_hash(content_hash: str, *, key: str | None = None) -> Seal:
    if not content_hash:
        raise SealError("Refusing to seal an empty content hash.")
    signature = hmac.new(
        _key_material(key), content_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return Seal(
        algorithm=ALGORITHM,
        key_id=key_id(key),
        content_hash=content_hash,
        signature=signature,
    )


def seal_document(document: Mapping[str, Any], *, key: str | None = None) -> Seal:
    """Seal a passport document, recomputing its hash rather than trusting it.

    A document that carries a `contentHash` which does not match its own body
    is either corrupt or forged; sealing it as-is would launder the problem.
    """
    body = {k: v for k, v in document.items() if k not in {"@context", "contentHash", "issuedAt", "seal"}}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    declared = document.get("contentHash")
    if declared and declared != computed:
        raise SealError(
            "Document contentHash does not match its body — refusing to seal. "
            f"declared={declared[:16]}… computed={computed[:16]}…"
        )
    return seal_hash(computed, key=key)


def verify(seal: Mapping[str, Any], content_hash: str, *, key: str | None = None) -> bool:
    """Constant-time verification. Unknown algorithms fail closed."""
    if seal.get("algorithm") != ALGORITHM:
        raise SealError(
            f"Unsupported seal algorithm {seal.get('algorithm')!r}; expected {ALGORITHM}. "
            "Failing closed rather than guessing."
        )
    if seal.get("contentHash") != content_hash:
        return False
    expected = hmac.new(
        _key_material(key), content_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, str(seal.get("signature", "")))
