"""RGPD — Liste des entreprises qui ont demandé à ne plus être contactées.

Stockée dans oppositions.csv (et non dans le cache) pour ne jamais être perdue par un nettoyage.
"""

import csv
from datetime import date

from .config import FICHIER_OPPOSITIONS

COLONNES = ["siren", "date", "motif"]


def lire():
    if not FICHIER_OPPOSITIONS.exists():
        return {}
    with open(FICHIER_OPPOSITIONS, encoding="utf-8", newline="") as f:
        return {ligne["siren"]: ligne for ligne in csv.DictReader(f)}


def ajouter(siren, motif=""):
    siren = "".join(c for c in siren if c.isdigit())[:9]
    if len(siren) != 9:
        raise SystemExit("Le SIREN doit contenir 9 chiffres.")
    if siren in lire():
        print(f"ℹ️  {siren} est déjà dans la liste d'opposition.")
        return
    nouveau = not FICHIER_OPPOSITIONS.exists()
    with open(FICHIER_OPPOSITIONS, "a", encoding="utf-8", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=COLONNES)
        if nouveau:
            ecrivain.writeheader()
        ecrivain.writerow({"siren": siren, "date": date.today().isoformat(), "motif": motif})
    print(f"🚫 {siren} ajouté à la liste d'opposition : il ne sera plus jamais proposé au contact.")
