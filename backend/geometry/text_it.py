"""Numeri nei testi per l'utente: virgola decimale all'italiana (350,0 cm, 1,4°)."""
import re

_NUM_UNIT = re.compile(r"(\d+)\.(\d+)(?=\s?(?:cm|mm|m²|m|°|%))")


def it(text: str) -> str:
    return _NUM_UNIT.sub(r"\1,\2", text)
