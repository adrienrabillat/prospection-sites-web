"""Base locale SQLite (prospection.sqlite) : tout ce que l'outil a trouvé, pour reprendre sans rien repayer.

Tables :
- candidats : un site d'entreprise par ligne (clé = domaine), avec sa visite et le verdict de l'IA
- memo      : réponses déjà obtenues (OpenStreetMap, Google Maps, découverte IA), par requête
- depenses  : chaque dépense Anthropic, en dollars
- compteurs : nombre d'appels par service et par mois (quota Google Maps)
- suivi     : ton suivi commercial (état, notes), par site. Ne supprime pas ce fichier.
"""

import json
import sqlite3
import threading
import time
from datetime import date, datetime

from .config import RACINE

FICHIER = RACINE / "prospection.sqlite"
ETATS = ["Nouveau", "À contacter", "Contacté", "À relancer", "Rendez-vous", "Client", "Pas intéressé", "Opposition"]
OPPOSITION = "Opposition"  # l'entreprise a demandé à ne plus être contactée : elle n'est plus jamais analysée

_connexion = None
_verrou = threading.RLock()


def connexion():
    global _connexion
    with _verrou:
        if _connexion is None:
            _connexion = sqlite3.connect(FICHIER, check_same_thread=False, timeout=30)
            _connexion.executescript("""
                CREATE TABLE IF NOT EXISTS candidats (cle TEXT PRIMARY KEY, ville TEXT, donnees TEXT, maj REAL);
                CREATE TABLE IF NOT EXISTS memo (cle TEXT PRIMARY KEY, donnees TEXT, maj REAL);
                CREATE TABLE IF NOT EXISTS depenses (jour TEXT, ville TEXT, etape TEXT, usd REAL);
                CREATE TABLE IF NOT EXISTS compteurs (nom TEXT, mois TEXT, nb INTEGER, PRIMARY KEY (nom, mois));
                CREATE TABLE IF NOT EXISTS suivi (cle TEXT PRIMARY KEY, etat TEXT, notes TEXT, maj TEXT);
            """)
        return _connexion


def _executer(sql, parametres=()):
    with _verrou:
        resultat = connexion().execute(sql, parametres).fetchall()
        connexion().commit()
        return resultat


# --- Candidats --------------------------------------------------------------------------------

def candidat(cle):
    lignes = _executer("SELECT donnees FROM candidats WHERE cle = ?", (cle,))
    return json.loads(lignes[0][0]) if lignes else None


def enregistrer(candidat_):
    _executer("INSERT OR REPLACE INTO candidats VALUES (?, ?, ?, ?)",
              (candidat_["cle"], candidat_["ville"], json.dumps(candidat_, ensure_ascii=False), time.time()))


def candidats(ville=None):
    """Tous les candidats (d'une ville, ou de toutes), avec leur suivi."""
    sql = "SELECT donnees FROM candidats" + (" WHERE ville = ?" if ville else "")
    suivis = {cle: (etat, notes) for cle, etat, notes in _executer("SELECT cle, etat, notes FROM suivi")}
    resultat = []
    for (donnees,) in _executer(sql, (ville,) if ville else ()):
        c = json.loads(donnees)
        c["suivi"], c["notes"] = suivis.get(c["cle"], ("Nouveau", ""))
        resultat.append(c)
    return resultat


def villes():
    return [v for (v,) in _executer("SELECT DISTINCT ville FROM candidats ORDER BY ville")]


# --- Réponses mémorisées ----------------------------------------------------------------------

def memo(cle, max_jours=30):
    lignes = _executer("SELECT donnees, maj FROM memo WHERE cle = ?", (cle,))
    if not lignes or time.time() - lignes[0][1] > max_jours * 86400:
        return None
    return json.loads(lignes[0][0])


def memoriser(cle, valeur):
    _executer("INSERT OR REPLACE INTO memo VALUES (?, ?, ?)", (cle, json.dumps(valeur, ensure_ascii=False), time.time()))


# --- Dépenses et quotas -----------------------------------------------------------------------

def depenser(ville, etape, usd):
    if usd:
        _executer("INSERT INTO depenses VALUES (?, ?, ?, ?)", (date.today().isoformat(), ville, etape, usd))


def depense_totale():
    return _executer("SELECT COALESCE(SUM(usd), 0) FROM depenses")[0][0]


def compteur(nom):
    lignes = _executer("SELECT nb FROM compteurs WHERE nom = ? AND mois = ?", (nom, date.today().strftime("%Y-%m")))
    return lignes[0][0] if lignes else 0


def incrementer(nom):
    _executer("""INSERT INTO compteurs VALUES (?, ?, 1)
                 ON CONFLICT (nom, mois) DO UPDATE SET nb = nb + 1""", (nom, date.today().strftime("%Y-%m")))


# --- Suivi commercial -------------------------------------------------------------------------

def noter_suivi(cle, etat, notes):
    _executer("INSERT OR REPLACE INTO suivi VALUES (?, ?, ?, ?)",
              (cle, etat or "Nouveau", notes or "", datetime.now().strftime("%Y-%m-%d %H:%M")))


def oppositions():
    return {cle for (cle,) in _executer("SELECT cle FROM suivi WHERE etat = ?", (OPPOSITION,))}
