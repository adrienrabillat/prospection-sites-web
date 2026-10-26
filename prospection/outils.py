"""Petites fonctions de texte partagées."""

import re
import unicodedata

FORMES_JURIDIQUES = {
    "sarl", "sas", "sasu", "eurl", "sa", "sci", "snc", "selarl", "selas", "scp", "scop",
    "sarlu", "ei", "eirl", "micro", "entreprise", "ets", "etablissements", "societe", "ste",
}
MOTS_VIDES = {"le", "la", "les", "l", "de", "du", "des", "d", "et", "a", "au", "aux", "en", "chez"}


def sans_accents(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c))


def normaliser(texte):
    """Minuscules, sans accents, ponctuation remplacée par des espaces."""
    texte = sans_accents(texte).lower().replace("'", " ").replace("’", " ")
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def mots_utiles(texte):
    """Mots d'un nom d'entreprise sans forme juridique ni mots vides."""
    return [m for m in normaliser(texte).split() if m not in FORMES_JURIDIQUES | MOTS_VIDES]


def slug(texte, separateur="-"):
    return separateur.join(normaliser(texte).split())


def contient_mot(texte, mot):
    """Vrai si `mot` (éventuellement plusieurs mots) apparaît entier dans `texte`."""
    return re.search(rf"\b{re.escape(normaliser(mot))}\b", normaliser(texte)) is not None


def chiffres(texte):
    return re.sub(r"\D", "", texte or "")


def telephone_national(telephone):
    """'+33 1 23 45 67 89' -> '0123456789' (ou '' si non reconnu)."""
    numero = chiffres(telephone)
    if numero.startswith("33") and len(numero) == 11:
        numero = "0" + numero[2:]
    return numero if len(numero) == 10 and numero.startswith("0") else ""
