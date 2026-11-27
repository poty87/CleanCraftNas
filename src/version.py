"""Dati del prodotto condivisi da app, installazione guidata e build."""

APP_NAME = "CleanCraftNas"
VERSION = "1.10.0"
REPO = "poty87/CleanCraftNas"
# non cambiarlo mai: è ciò che permette a una nuova versione di sostituire quella installata
# (anche le versioni 1.0–1.1, che si chiamavano "Pulizia cestino Lightcraft")
UPGRADE_CODE = "{A12F739D-0076-4137-9AA2-477F6CC22D4C}"
REG_KEY = r"Software\CleanCraftNas"  # scelte fatte durante l'installazione (lingua, collegamento sul Desktop)


def parse_version(text):
    """"v1.10.2" → (1, 10, 2); parti non numeriche contano 0."""
    parts = []
    for p in str(text).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))
