"""Behavioral tests for the price-`$`-mask helper (M1).

The mask runs on text nodes BEFORE KaTeX auto-render and is reverted after.
Genuine inline/display LaTeX (`$1/N$`, `$2\\pi$`, `$$2x$$`) must survive the
mask so KaTeX renders it; real currency (`$5`, `$10.99`) must be masked so the
auto-render delimiter scan skips it.

We execute the REAL ``_maskPriceDollars`` / ``_unmaskPriceDollars`` from each
surface file in Node against a jsdom-free DOM stub, then inspect what KaTeX's
delimiter scan would see (the masked string) vs the round-tripped output.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2].parent
_NODE = shutil.which("node")

SURFACES = {
    "home": "website/features/user_home/js/home.js",
    "user_zettels": "website/features/user_zettels/js/user_zettels.js",
}

# (input, list of substrings that MUST remain a live `$...$` math span after
#  masking — i.e. NOT masked) , (substrings that MUST be masked / not paired).
# We assert on the masked string: a math span keeps real `$` delimiters; a
# currency `$` is replaced by the sentinel so KaTeX won't pair it.
MUST_BE_MATH = [
    "$1/N$",
    "$2\\pi$",
    "$3x+1$",
    "$x_1$",
    "$\\alpha$",
    "$$\\sum_{i=1}^{n} i$$",
    "$E=mc^2$",
    "The ratio $1/N$ converges.",
    "$$2x$$",
]
MUST_BE_CURRENCY = [
    "it costs $5",
    "$10.99 per unit",
    "$1,000,000 budget",
    "between $5 and $10",
    "the bill was $5.",
    "price: $42",
]
# Mixed: first two currency masked, the $1/N$ paired/rendered.
MIXED = "$5 to $10 for the $1/N$ ratio"
ESCAPED = "\\$5 costs nothing"


def _extract_helpers(js: str) -> str:
    """Pull the two helper function bodies out of the surface file so they can
    run standalone in Node (the file is an IIFE that needs a browser)."""
    out = []
    sigs = {
        "_maskPriceDollarsStr": r"function _maskPriceDollarsStr\(s\)\s*\{",
        "_maskPriceDollars": r"function _maskPriceDollars\(rootEl\)\s*\{",
        "_unmaskPriceDollars": r"function _unmaskPriceDollars\(rootEl\)\s*\{",
    }
    for name in ("_maskPriceDollarsStr", "_maskPriceDollars", "_unmaskPriceDollars"):
        m = re.search(sigs[name], js)
        assert m, name + " not found"
        i = m.end()
        depth = 1
        while depth:
            c = js[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        out.append(js[m.start():i])
    return "\n".join(out)


def _run_mask(js_helpers: str, text: str) -> dict:
    harness = textwrap.dedent(
        """
        // Minimal single-text-node DOM stub mirroring TreeWalker SHOW_TEXT.
        global.NodeFilter = { SHOW_TEXT: 4 };
        const TEXT = %s;
        function makeRoot(value) {
          const node = { nodeValue: value };
          return {
            _node: node,
            _served: false,
          };
        }
        global.document = {
          createTreeWalker(rootEl) {
            return {
              nextNode() {
                if (rootEl._served) return null;
                rootEl._served = true;
                return rootEl._node;
              },
            };
          },
        };
        %s
        const root = makeRoot(TEXT);
        _maskPriceDollars(root);
        const masked = root._node.nodeValue;
        // reset walker, unmask
        root._served = false;
        _unmaskPriceDollars(root);
        const roundtrip = root._node.nodeValue;
        console.log(JSON.stringify({ masked, roundtrip }));
        """
    ) % (json.dumps(text), js_helpers)
    proc = subprocess.run(
        [_NODE, "-e", harness],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _katex_delims(s: str) -> int:
    """Count live `$` delimiters KaTeX auto-render would still pair on (i.e.
    real `$`, not the mask sentinel ``﹩``)."""
    return s.count("$")


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("surface", sorted(SURFACES))
@pytest.mark.parametrize("text", MUST_BE_MATH)
def test_math_spans_survive_mask(surface, text):
    js = (ROOT / SURFACES[surface]).read_text(encoding="utf-8")
    out = _run_mask(_extract_helpers(js), text)
    # All real `$` delimiters preserved → KaTeX still pairs and renders.
    assert out["masked"].count("$") == text.count("$"), out
    assert "﹩" not in out["masked"], out
    assert out["roundtrip"] == text


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("surface", sorted(SURFACES))
@pytest.mark.parametrize("text", MUST_BE_CURRENCY)
def test_currency_is_masked(surface, text):
    js = (ROOT / SURFACES[surface]).read_text(encoding="utf-8")
    out = _run_mask(_extract_helpers(js), text)
    # Every currency `$` masked → KaTeX delimiter scan sees none.
    assert out["masked"].count("$") == 0, out
    assert "﹩" in out["masked"], out
    # round-trip restores the original literal
    assert out["roundtrip"] == text


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_mixed_currency_and_math(surface):
    js = (ROOT / SURFACES[surface]).read_text(encoding="utf-8")
    out = _run_mask(_extract_helpers(js), MIXED)
    # the $1/N$ pair survives (2 real `$`), the two leading currency `$` masked
    assert out["masked"].count("$") == 2, out
    assert out["masked"].count("﹩") == 2, out
    # the surviving pair must wrap 1/N
    assert "$1/N$" in out["masked"], out
    assert out["roundtrip"] == MIXED


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_escaped_dollar_stays_literal(surface):
    js = (ROOT / SURFACES[surface]).read_text(encoding="utf-8")
    out = _run_mask(_extract_helpers(js), ESCAPED)
    # Per spec: an escaped \$5 stays a literal `\$5` — it is NOT a math
    # delimiter (so KaTeX won't render it) and NOT double-masked. The escape
    # is preserved verbatim and round-trips unchanged.
    assert out["masked"] == ESCAPED, out
    assert "﹩" not in out["masked"], out
    assert out["roundtrip"] == ESCAPED


def test_both_surfaces_mask_helpers_are_identical():
    bodies = []
    for rel in SURFACES.values():
        js = (ROOT / rel).read_text(encoding="utf-8")
        bodies.append(_extract_helpers(js).strip())
    assert bodies[0] == bodies[1], "home.js / user_zettels.js mask helpers drifted"
