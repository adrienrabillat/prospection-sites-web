"""Suivi commercial (contacté, à relancer…) et notes, par SIREN.

Stocké dans suivi.sqlite, séparé du cache : ces données sont les tiennes et ne doivent jamais être perdues.
"""

import sqlite3
from datetime import datetime

from .config import RACINE

FICHIER_SUIVI = RACINE / "suivi.sqlite"
ETATS = ["Nouveau", "À contacter", "Contacté", "À relancer", "Rendez-vous", "Client", "Pas intéressé", "Opposition"]
OPPOSITION = "Opposition"

_connexion = None


def connexion():
    global _connexion
    if _connexion is None:
        _connexion = sqlite3.connect(FICHIER_SUIVI, check_same_thread=False)
        _connexion.execute("CREATE TABLE IF NOT EXISTS suivi (siren TEXT PRIMARY KEY, etat TEXT, notes TEXT, maj TEXT)")
    return _connexion


def lire(siren):
    ligne = connexion().execute("SELECT etat, notes, maj FROM suivi WHERE siren = ?", (siren,)).fetchone()
    return {"suivi": ligne[0], "notes": ligne[1], "suivi_maj": ligne[2]} if ligne else \
        {"suivi": "Nouveau", "notes": "", "suivi_maj": ""}


def ecrire(siren, etat, notes):
    connexion().execute("INSERT OR REPLACE INTO suivi VALUES (?, ?, ?, ?)",
                        (siren, etat or "", notes or "", datetime.now().strftime("%Y-%m-%d %H:%M")))
    connexion().commit()
