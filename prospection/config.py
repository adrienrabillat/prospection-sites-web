"""Chargement de la configuration (YAML) et des clés (.env)."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_DATA = RACINE / "data"
FICHIER_CACHE = RACINE / "cache.sqlite"
FICHIER_OPPOSITIONS = RACINE / "oppositions.csv"

load_dotenv(RACINE / ".env")


def lire_yaml(nom):
    with open(RACINE / nom, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = lire_yaml("config.yaml")
EMPREINTES = lire_yaml("empreintes.yaml")
ACTIVITES = lire_yaml("activites.yaml")


def cle(nom):
    """Renvoie la clé d'API si elle est renseignée dans .env, sinon None."""
    valeur = os.getenv(nom, "").strip()
    return valeur or None


def enregistrer_cle(nom, valeur):
    """Écrit (ou remplace) NOM=valeur dans .env et l'applique tout de suite."""
    fichier = RACINE / ".env"
    if not fichier.exists():
        fichier.write_text((RACINE / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    nouvelle = f"{nom}={valeur.strip()}"
    for i, ligne in enumerate(lignes):
        if ligne.split("=", 1)[0].strip() == nom:
            lignes[i] = nouvelle
            break
    else:
        lignes.append(nouvelle)
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    fichier.chmod(0o600)  # lisible par toi seul
    os.environ[nom] = valeur.strip()


CONTACT = cle("CONTACT_EMAIL")
USER_AGENT = "OutilProspectionFreelance/1.0 (python-requests; usage ponctuel"
USER_AGENT += f"; contact : {CONTACT})" if CONTACT else ")"
