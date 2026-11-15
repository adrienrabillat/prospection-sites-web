"""Accès réseau : pause entre requêtes par hôte, reprises avec backoff, User-Agent honnête."""

import time
from urllib.parse import urlparse

import requests

from .config import CONFIG, USER_AGENT

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})

_derniere_requete = {}  # hôte -> horodatage


class ErreurAPI(Exception):
    pass


def _patienter(hote):
    delai = CONFIG["debit"].get(hote, CONFIG["debit"]["defaut"])
    attente = _derniere_requete.get(hote, 0) + delai - time.time()
    if attente > 0:
        time.sleep(attente)
    _derniere_requete[hote] = time.time()


def _attente_backoff(reponse, essai):
    """Respecte Retry-After si fourni, sinon backoff exponentiel (2, 4, 8… s)."""
    if reponse is not None:
        retry_after = reponse.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(int(retry_after), 120)
    return 2 ** (essai + 1)


def appel_api(url, params=None, entetes=None, tentatives=4, timeout=None, donnees=None):
    """GET (ou POST si `donnees`) sur une API JSON, avec reprise sur 429 / 5xx / erreur réseau."""
    hote = urlparse(url).hostname
    for essai in range(tentatives):
        _patienter(hote)
        reponse = None
        try:
            reponse = session.request("POST" if donnees else "GET", url, params=params, data=donnees,
                                      headers=entetes, timeout=timeout or CONFIG["timeout_api"])
            if reponse.status_code == 429 or reponse.status_code >= 500:
                raise ErreurAPI(f"HTTP {reponse.status_code}")
            if reponse.status_code >= 400:
                raise ErreurAPI(f"HTTP {reponse.status_code} : {reponse.text[:300]}")
            return reponse.json()
        except (requests.RequestException, ErreurAPI) as erreur:
            definitive = isinstance(erreur, ErreurAPI) and reponse is not None \
                and 400 <= reponse.status_code < 500 and reponse.status_code != 429
            if definitive or essai == tentatives - 1:
                raise ErreurAPI(f"{hote} : {erreur}") from erreur
            pause = _attente_backoff(reponse, essai)
            print(f"    ⏳ {hote} : {erreur}, nouvel essai dans {pause} s")
            time.sleep(pause)
