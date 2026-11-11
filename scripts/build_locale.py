"""Compiles locale_src/catalog.py into Django's .mo files. No gettext tools needed."""
import sys
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locale_src.catalog import CATALOG  # noqa: E402


def main():
    for index, code in enumerate(("ar", "fr")):
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8", "Language": code}
        for msgid, translations in CATALOG.items():
            po.append(polib.POEntry(msgid=msgid, msgstr=translations[index]))
        target = ROOT / "locale" / code / "LC_MESSAGES"
        target.mkdir(parents=True, exist_ok=True)
        po.save_as_mofile(str(target / "django.mo"))
    print(f"Compiled {len(CATALOG)} texts.")


if __name__ == "__main__":
    main()
