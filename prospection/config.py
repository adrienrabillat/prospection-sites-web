"""Chargement de la configuration (YAML) et des clés (.env)."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_DATA = RACINE / "data"

load_dotenv(RACINE / ".env")


def lire_yaml(nom):
    with open(RACINE / nom, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = lire_yaml("config.yaml")
EMPREINTES = lire_yaml("empreintes.yaml")


def cle(nom):
    """Renvoie la clé d'API si elle est renseignée dans .env, sinon None."""
    valeur = os.getenv(nom, "").strip()
    return valeur or None


def client_anthropic():
    """Client de l'API Claude. Une clé non rattachée à un espace de travail a besoin de ANTHROPIC_WORKSPACE_ID."""
    import anthropic
    espace = cle("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(api_key=cle("ANTHROPIC_API_KEY"), max_retries=4, timeout=300,
                               default_headers={"anthropic-workspace-id": espace} if espace else None)


def verifier_cle_anthropic(modele):
    """Renvoie None si la clé fonctionne (appel gratuit), sinon l'explication de l'erreur."""
    import anthropic
    if not cle("ANTHROPIC_API_KEY"):
        return "il manque ANTHROPIC_API_KEY dans le fichier .env"
    try:
        client_anthropic().models.retrieve(modele)
        return None
    except anthropic.AuthenticationError:
        return "la clé ANTHROPIC_API_KEY du fichier .env est refusée (invalide ou révoquée)"
    except anthropic.APIStatusError as erreur:
        if "workspace" in str(erreur):
            return ("cette clé n'est rattachée à aucun espace de travail (workspace). Crée une clé d'API dans la "
                    "Console Anthropic (API keys), ou ajoute ANTHROPIC_WORKSPACE_ID=wrkspc_… dans .env")
        return f"l'API Anthropic répond HTTP {erreur.status_code} : {erreur.message}"
    except anthropic.APIConnectionError:
        return "connexion impossible à l'API Anthropic"


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
USER_AGENT = "OutilProspectionFreelance/2.0 (python-requests; usage ponctuel"
USER_AGENT += f"; contact : {CONTACT})" if CONTACT else ")"
