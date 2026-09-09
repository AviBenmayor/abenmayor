"""GTM-105 finding F: google_places.py's GOOGLE_TYPES claims to mirror
webmap/server.js's GT map but the two had drifted (JS omitted `preschool`,
`medical_lab`, and `fitness_center`). Parse the JS map with a small regex
(no JS runtime dependency) and assert equality against the Python map, which
is the source of truth."""
import pathlib
import re

from loci.validation.google_places import GOOGLE_TYPES

SERVER_JS = pathlib.Path(__file__).resolve().parents[1] / "webmap" / "server.js"


def _parse_js_gt_map(text: str) -> dict[str, list[str]]:
    """Extract the `const GT={...};` object literal as {category: [types]}."""
    m = re.search(r"const\s+GT\s*=\s*\{(.*?)\}\s*;", text, re.DOTALL)
    assert m, "could not find `const GT={...};` in webmap/server.js"
    body = m.group(1)
    pairs = re.findall(r"(\w+)\s*:\s*\[([^\]]*)\]", body)
    assert pairs, "found the GT object but no category:[...] entries in it"
    out: dict[str, list[str]] = {}
    for key, items in pairs:
        types = [t.strip().strip("'\"") for t in items.split(",") if t.strip()]
        out[key] = types
    return out


def test_js_gt_map_matches_python_google_types():
    js_map = _parse_js_gt_map(SERVER_JS.read_text())
    assert js_map == GOOGLE_TYPES
