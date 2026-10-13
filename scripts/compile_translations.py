"""Compila locale/catalog.py a archivos .po/.mo de Django sin necesitar GNU gettext.

Uso:  .venv/Scripts/python scripts/compile_translations.py
"""

import importlib.util
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("catalog", ROOT / "locale" / "catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

for index, lang in enumerate(catalog.LANGS):
    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Language": lang,
        "Plural-Forms": "nplurals=2; plural=(n != 1);",
    }
    for msgid, translations in catalog.CATALOG.items():
        po.append(polib.POEntry(msgid=msgid, msgstr=translations[index]))
    folder = ROOT / "locale" / lang / "LC_MESSAGES"
    folder.mkdir(parents=True, exist_ok=True)
    po.save(str(folder / "django.po"))
    po.save_as_mofile(str(folder / "django.mo"))
    print(f"{lang}: {len(po)} textos")
