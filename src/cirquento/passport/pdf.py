"""Render a passport to PDF with nothing but the standard library.

A PDF renderer is an odd thing to hand-write. The reason is the same constraint
that shapes the rest of the offline path: `reportlab` and `weasyprint` are not
installable in every environment a reviewer will use, and "the PDF feature
works if pip works" is not a working feature. This produces a real, valid PDF
— openable in any viewer — in ~150 lines with zero dependencies.

It is deliberately typographically plain. The passport is a regulatory artefact
whose job is to be readable and verifiable, and the honest version of that is a
clean single-column document with the content hash printed on it, not a
brochure.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

PAGE_W, PAGE_H = 595, 842  # A4 in points
MARGIN = 56
LEADING = 15


def _escape(text: str) -> str:
    """Escape for a PDF literal string, and drop anything non-Latin-1.

    The base-14 fonts are single-byte. Rather than emit mojibake for a German
    umlaut or an en dash, characters outside the encoding are transliterated to
    a safe equivalent — a passport that renders wrong is worse than one that
    renders plainly.
    """
    swaps = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": "-",
        "\u2192": "->", "\u2265": ">=", "\u2264": "<=", "\u00d7": "x",
    }
    for bad, good in swaps.items():
        text = text.replace(bad, good)
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, width_chars: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class _Content:
    """Accumulates a text stream, breaking pages when it runs out of room."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.y = PAGE_H - MARGIN

    def _ensure(self, needed: int) -> None:
        if self.y - needed < MARGIN:
            self.pages.append([])
            self.y = PAGE_H - MARGIN

    def line(self, text: str, size: int = 10, font: str = "F1", gap: int = LEADING) -> None:
        self._ensure(gap)
        self.pages[-1].append(
            f"BT /{font} {size} Tf {MARGIN} {self.y} Td ({_escape(text)}) Tj ET"
        )
        self.y -= gap

    def rule(self) -> None:
        self._ensure(10)
        self.pages[-1].append(
            f"0.85 0.85 0.84 RG 0.8 w {MARGIN} {self.y + 6} m {PAGE_W - MARGIN} {self.y + 6} l S"
        )
        self.y -= 10

    def paragraph(self, text: str, size: int = 10, width: int = 88) -> None:
        for chunk in _wrap(text, width):
            self.line(chunk, size=size)

    def kv(self, key: str, value: str) -> None:
        self._ensure(LEADING)
        self.pages[-1].append(
            f"BT /F2 10 Tf {MARGIN} {self.y} Td ({_escape(key)}) Tj ET"
        )
        self.pages[-1].append(
            f"BT /F1 10 Tf {MARGIN + 170} {self.y} Td ({_escape(value)}) Tj ET"
        )
        self.y -= LEADING


def _build_pdf(pages: Sequence[Sequence[str]]) -> bytes:
    """Assemble objects and a correct xref table.

    Byte offsets in the xref must be exact or viewers reject the file, so the
    document is serialised once while recording positions, not guessed.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    # The /Pages object does not exist yet, but every page must reference it as
    # its parent, so its object number is computed ahead: current count, plus
    # two objects per page (content stream + page), plus one for itself.
    # The assertion below is load-bearing. The first version of this line was
    # off by one, and the assert caught it instead of emitting a PDF that some
    # viewers open and others silently reject.
    pages_obj_number = len(objects) + 2 * len(pages) + 1
    page_numbers: list[int] = []
    for ops in pages:
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_obj_number, PAGE_W, PAGE_H, font_regular, font_bold, content)
        )
        page_numbers.append(page)

    kids = b" ".join(b"%d 0 R" % n for n in page_numbers)
    pages_obj = add(b"<< /Type /Pages /Count %d /Kids [%s] >>" % (len(page_numbers), kids))
    assert pages_obj == pages_obj_number, "page tree object number drifted"
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref_at,
    )
    return bytes(out)


def render_passport(
    passport: Mapping[str, Any],
    *,
    seal: Mapping[str, Any] | None = None,
    recommendations: Sequence[Mapping[str, Any]] = (),
) -> bytes:
    c = _Content()

    c.line("Digital Product Passport", size=18, font="F2", gap=24)
    c.line(f"{passport.get('productName', '')} - {passport.get('productId', '')}", size=11)
    c.rule()

    c.line("Summary", size=12, font="F2", gap=18)
    c.kv("Circularity score", f"{passport.get('circularityScore', 0):.0f} / 100")
    c.kv("Ruleset version", str(passport.get("rulesetVersion", "")))
    c.kv("Components", str(passport.get("componentCount", 0)))
    c.kv("Total mass", f"{passport.get('totalMassKg', 0):.3f} kg")
    c.kv("Content hash", str(passport.get("contentHash", ""))[:48])
    if seal:
        c.kv("Seal", f"{seal.get('algorithm')} / {seal.get('keyId')}")
    c.y -= 6

    c.line("Score breakdown", size=12, font="F2", gap=18)
    for name, d in sorted(passport.get("dimensions", {}).items()):
        c.kv(name.replace("_", " ").title(), f"{d.get('value', 0):.0f} / 100  (weight {d.get('weight', 0):.2f})")
        for finding in list(d.get("findings", []))[:2]:
            c.paragraph(f"    - {finding}", size=9, width=95)
    c.y -= 6

    c.line("Material composition", size=12, font="F2", gap=18)
    comp = passport.get("materialComposition", {})
    for code, pct in sorted(comp.items(), key=lambda kv: -float(kv[1]))[:14]:
        if float(pct) >= 0.1:
            c.kv(code, f"{float(pct):.2f} %")
    c.y -= 6

    # Gaps are printed on the artefact itself. A passport that only shows what
    # is known lets the reader assume the rest was checked.
    c.line("Declared data gaps", size=12, font="F2", gap=18)
    gaps = passport.get("dataGaps", {})
    c.kv("Unclassified lines", str(gaps.get("unclassifiedLines", 0)))
    c.kv("Lines without recycled evidence", str(gaps.get("missingRecycledContent", 0)))
    c.paragraph(
        "Lines without evidence are scored as 0% recycled content, never as an average. "
        "A gap is reported as a gap.",
        size=9,
    )
    c.y -= 6

    if recommendations:
        c.line("Recommendations (counterfactuals)", size=12, font="F2", gap=18)
        for r in recommendations[:5]:
            marker = "conditional" if r.get("conditional") else "design change"
            c.paragraph(
                f"+{r.get('delta', 0):.0f} pts [{marker}] {r.get('action', '')}", size=10
            )
            c.paragraph(f"    {r.get('rationale', '')}", size=9, width=95)
        c.y -= 6

    c.line("Explanation", size=12, font="F2", gap=18)
    c.paragraph(str(passport.get("explanation", "")), size=10)

    c.rule()
    c.paragraph(
        "Generated by Cirquento. Every figure is derived by a deterministic, versioned rule "
        "engine from source rows; no value on this document was produced by a language model.",
        size=8,
    )
    return _build_pdf(c.pages)
