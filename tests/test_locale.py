import re
from pathlib import Path

from locale_src.catalog import CATALOG

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ["accounts", "audit", "catalog", "inventory", "ledger", "parties", "reports", "system"]


def used_texts():
    found = set()
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'translate\s+"([^"]+)"', text))
        found |= set(re.findall(r"translate\s+'([^']+)'", text))
    for folder in SOURCE_DIRS:
        for path in (ROOT / folder).rglob("*.py"):
            if "migrations" not in path.parts:
                found |= set(re.findall(r'\b_\("([^"]+)"\)', path.read_text(encoding="utf-8")))
    return found


def test_every_text_has_arabic_and_french():
    missing = sorted(used_texts() - set(CATALOG))
    assert not missing, missing
    assert all(ar.strip() and fr.strip() for ar, fr in CATALOG.values())


def test_placeholders_survive_translation():
    for key, (ar, fr) in CATALOG.items():
        wanted = sorted(re.findall(r"%\(\w+\)[sd]", key))
        assert sorted(re.findall(r"%\(\w+\)[sd]", ar)) == wanted, key
        assert sorted(re.findall(r"%\(\w+\)[sd]", fr)) == wanted, key
