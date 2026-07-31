"""Inline the generated data into a single, shareable HTML file.

The published console loads `data.js` as a sibling file, which is right for
GitHub Pages and wrong for every other way people actually look at a demo:
emailed, dropped in a chat, opened from a USB stick. Those all produce a page
of empty placeholders, which reads as "broken" rather than "missing a file".

So the shareable artefact is built, not hand-maintained, from exactly the same
generated data as the hosted page.
"""

from __future__ import annotations

import argparse
from pathlib import Path

TAG = '<script src="data.js"></script>'


def main() -> int:
    p = argparse.ArgumentParser(description="Build a single-file console.")
    p.add_argument("--html", type=Path, default=Path("docs/index.html"))
    p.add_argument("--data", type=Path, default=Path("docs/data.js"))
    p.add_argument("--out", type=Path, default=Path("docs/console.standalone.html"))
    args = p.parse_args()

    html = args.html.read_text(encoding="utf-8")
    data = args.data.read_text(encoding="utf-8")

    if TAG not in html:
        raise SystemExit(
            f"Expected {TAG!r} in {args.html}. The console template changed; "
            "update this script rather than shipping a page that renders blank."
        )

    # Guard against the one way this can silently corrupt: a literal closing
    # script tag inside the data would end the inlined block early.
    if "</script" in data:
        data = data.replace("</script", "<\\/script")

    args.out.write_text(
        html.replace(TAG, "<script>\n" + data + "</script>"), encoding="utf-8"
    )
    print(f"Wrote {args.out} ({args.out.stat().st_size:,} bytes, self-contained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
