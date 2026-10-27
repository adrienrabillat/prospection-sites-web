"""Cache local SQLite : permet de reprendre un traitement là où il s'est arrêté.

Tables :
- entreprises : fiche de l'API de l'État, par SIREN
- analyses    : résultat des étapes 2 et 3 (site trouvé + analyse), par SIREN
- urls        : réponse d'une URL testée (statut, HTML…), par URL
- api         : réponses d'APIs externes (SerpAPI, Brave, PageSpeed), par requête
- qualifications : verdict de l'agent IA, par SIREN (payant : à garder)
- compteurs   : nombre d'appels réels par API et par mois (quotas), dépense IA en micro-dollars
"""

import json
import sqlite3
import time
from datetime import date

from .config import CONFIG, FICHIER_CACHE

_connexion = None


def connexion():
    global _connexion
    if _connexion is None:
        _connexion = sqlite3.connect(FICHIER_CACHE, check_same_thread=False)  # l'interface Streamlit est multi-thread
        _connexion.executescript("""
            CREATE TABLE IF NOT EXISTS entreprises (siren TEXT PRIMARY KEY, donnees TEXT, maj REAL);
            CREATE TABLE IF NOT EXISTS analyses (siren TEXT PRIMARY KEY, donnees TEXT, maj REAL);
            CREATE TABLE IF NOT EXISTS urls (url TEXT PRIMARY KEY, donnees TEXT, maj REAL);
            CREATE TABLE IF NOT EXISTS api (cle TEXT PRIMARY KEY, donnees TEXT, maj REAL);
            CREATE TABLE IF NOT EXISTS qualifications (siren TEXT PRIMARY KEY, donnees TEXT, maj REAL);
            CREATE TABLE IF NOT EXISTS compteurs (api TEXT, mois TEXT, nb INTEGER, PRIMARY KEY (api, mois));
        """)
    return _connexion


def lire(table, cle, max_jours=None):
    """Renvoie la valeur en cache, ou None si absente ou trop vieille."""
    max_jours = CONFIG.get("cache_jours", 30) if max_jours is None else max_jours
    colonne = {"entreprises": "siren", "analyses": "siren", "qualifications": "siren", "urls": "url", "api": "cle"}[table]
    ligne = connexion().execute(
        f"SELECT donnees, maj FROM {table} WHERE {colonne} = ?", (cle,)).fetchone()
    if not ligne or time.time() - ligne[1] > max_jours * 86400:
        return None
    return json.loads(ligne[0])


def ecrire(table, cle, valeur):
    connexion().execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)",
                        (cle, json.dumps(valeur, ensure_ascii=False), time.time()))
    connexion().commit()


def tout(table):
    """Toutes les valeurs d'une table, sans tenir compte de leur âge : {clé: valeur}."""
    return {ligne[0]: json.loads(ligne[1]) for ligne in connexion().execute(f"SELECT * FROM {table}")}


def compteur(api):
    mois = date.today().strftime("%Y-%m")
    ligne = connexion().execute(
        "SELECT nb FROM compteurs WHERE api = ? AND mois = ?", (api, mois)).fetchone()
    return ligne[0] if ligne else 0


def incrementer(api, n=1):
    mois = date.today().strftime("%Y-%m")
    connexion().execute("""
        INSERT INTO compteurs VALUES (?, ?, ?)
        ON CONFLICT (api, mois) DO UPDATE SET nb = nb + excluded.nb""", (api, mois, n))
    connexion().commit()
