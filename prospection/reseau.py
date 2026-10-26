"""Accès réseau : pause entre requêtes par hôte, reprises avec backoff, User-Agent honnête."""

import re
import socket
import time
from urllib.parse import urlparse

import requests
import urllib3

from .config import CONFIG, USER_AGENT

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TAILLE_MAX_PAGE = 30_000_000  # octets lus au maximum (certaines pages embarquent images et PDF en base64)
BASE64_LONG = re.compile(r"[A-Za-z0-9+/=]{1000,}")

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


def dns_existe(domaine):
    try:
        socket.getaddrinfo(domaine, 443)
        return True
    except (socket.gaierror, UnicodeError):
        return False


def _decoder(contenu, reponse):
    if reponse.encoding and "charset" in reponse.headers.get("Content-Type", "").lower():
        try:
            return contenu.decode(reponse.encoding, errors="replace")
        except LookupError:
            pass
    try:
        return contenu.decode("utf-8")
    except UnicodeDecodeError:
        return contenu.decode("cp1252", errors="replace")


def telecharger_page(url, tentatives=1):
    """Télécharge une page web (une seule requête GET, redirections suivies).

    Renvoie un dict : ok, statut, url_finale, html, entetes, duree, ssl_invalide, erreur.
    Ne lève jamais d'exception : une erreur est un résultat comme un autre (site cassé).
    """
    hote = urlparse(url).hostname or ""
    resultat = {"url": url, "ok": False, "statut": None, "url_finale": url, "html": "",
                "entetes": {}, "duree": None, "ssl_invalide": False, "erreur": None}
    verifier_ssl = True
    for essai in range(tentatives + 1):
        _patienter(hote)
        try:
            with session.get(url, timeout=CONFIG["timeout_site"], verify=verifier_ssl,
                             stream=True, allow_redirects=True) as reponse:
                contenu = b""
                for morceau in reponse.iter_content(65536):
                    contenu += morceau
                    if len(contenu) > TAILLE_MAX_PAGE:
                        break
                resultat.update(
                    statut=reponse.status_code, url_finale=reponse.url,
                    entetes={k.lower(): v for k, v in reponse.headers.items()},
                    duree=round(reponse.elapsed.total_seconds(), 2), erreur=None,  # délai jusqu'aux en-têtes
                    html=BASE64_LONG.sub("", _decoder(contenu, reponse)) if reponse.status_code < 400 else "")
                if reponse.status_code in (429, 502, 503, 504) and essai < tentatives:
                    time.sleep(min(_attente_backoff(reponse, essai), 5))  # un site n'est pas une API : on n'attend pas longtemps
                    continue
                resultat["ok"] = reponse.status_code < 400
                return resultat
        except requests.exceptions.SSLError as erreur:
            if verifier_ssl:  # certificat invalide : on retente sans vérifier pour voir le site
                resultat["ssl_invalide"] = True
                verifier_ssl = False
                continue
            resultat["erreur"] = f"SSL : {erreur.__class__.__name__}"
        except requests.exceptions.ConnectionError as erreur:
            texte = str(erreur)
            if "NameResolution" in texte or "getaddrinfo" in texte or "nodename" in texte:
                resultat["erreur"] = "DNS"
                return resultat
            resultat["erreur"] = "Connexion impossible"
        except requests.exceptions.Timeout:
            resultat["erreur"] = "Délai dépassé"
        except requests.RequestException as erreur:
            resultat["erreur"] = erreur.__class__.__name__
        if essai < tentatives and resultat["erreur"] != "Délai dépassé":
            time.sleep(2)
    return resultat
