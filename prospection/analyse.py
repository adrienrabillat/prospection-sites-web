"""Étape 3 — Analyser un site actif à partir de la page d'accueil déjà téléchargée.

Aucune requête supplémentaire, sauf le score PageSpeed (optionnel, clé PAGESPEED_API_KEY).
"""

import re
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import cache
from .config import CONFIG, EMPREINTES, cle
from .reseau import ErreurAPI, appel_api

EMAILS_IGNORES = ("example.", "sentry", "wixpress", "domain.", "email.com", "votre", "nom@", "@2x", ".png", ".jpg",
                  ".webp", ".gif", ".svg")
# Messageries grand public : une adresse chez elles est celle de l'entreprise (sinon : hébergeur, agence…)
WEBMAILS = ("gmail.com", "hotmail.fr", "hotmail.com", "outlook.fr", "outlook.com", "live.fr", "yahoo.fr", "yahoo.com",
            "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "neuf.fr", "laposte.net", "icloud.com", "bbox.fr", "aol.com")


def _version(texte):
    trouve = re.search(r"(\d+(?:\.\d+)+)", texte or "")
    return trouve.group(1) if trouve else ""


def _version_inferieure(version, seuil):
    def en_tuple(v):
        return tuple(int(x) for x in v.split(".") if x.isdigit())
    return bool(version) and en_tuple(version) < en_tuple(seuil)


def detecter_cms(html, entetes, generator):
    html_min = html.lower()
    for nom, regles in EMPREINTES["cms"].items():
        if any(m.lower() in html_min for m in regles.get("html", [])) \
                or any(e.startswith(p) for p in regles.get("entetes", []) for e in entetes) \
                or (regles.get("generator") and re.search(regles["generator"], generator, re.I)):
            return nom, regles.get("gamme", "standard")
    return "Inconnu / sur mesure", "standard"


def details_wordpress(html):
    theme = re.search(r"/wp-content/themes/([\w.-]+)/", html)
    builders = [nom for nom, motifs in EMPREINTES["page_builders"].items()
                if any(m.lower() in html.lower() for m in motifs)]
    # Seuls ces fichiers portent la version de WordPress (les autres ?ver= sont ceux des bibliothèques)
    version = re.search(r"/wp-includes/(?:css/dist/block-library/style(?:\.min)?\.css|js/wp-emoji-release\.min\.js"
                        r"|js/wp-embed\.min\.js)\?ver=(\d+\.\d+(?:\.\d+)?)", html)
    return (theme.group(1) if theme else ""), builders, (version.group(1) if version else "")


def annee_copyright(texte):
    annees = [int(a) for a in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", texte, re.I)]
    return max(annees) if annees else None


def emails(html, domaine_site):
    """Adresses du domaine du site ou d'une messagerie grand public (pas celles de l'hébergeur ou de l'agence)."""
    trouves = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", html, re.I)
    propres = []
    for adresse in (e.lower() for e in trouves):
        domaine = adresse.split("@")[1]
        if any(i in adresse for i in EMAILS_IGNORES):
            continue
        if domaine in WEBMAILS or domaine == domaine_site or domaine_site.endswith("." + domaine):
            propres.append(adresse)
    return list(dict.fromkeys(propres))


def score_pagespeed(url):
    cle_api = cle("PAGESPEED_API_KEY")
    if not cle_api:
        return None
    resultat = cache.lire("api", f"pagespeed:{url}")
    if resultat is None:
        try:
            reponse = appel_api("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                                {"url": url, "strategy": "mobile", "category": "performance", "key": cle_api},
                                timeout=90, tentatives=2)
            score = reponse["lighthouseResult"]["categories"]["performance"]["score"]
            resultat = {"score": round(score * 100) if score is not None else None}
        except (ErreurAPI, KeyError) as erreur:
            print(f"    ⚠️  PageSpeed : {str(erreur).replace(cle_api, '***')}")
            return None
        cache.ecrire("api", f"pagespeed:{url}", resultat)
    return resultat["score"]


def analyser(accueil, html_mentions="", avec_pagespeed=True):
    html = accueil["html"]
    soupe = BeautifulSoup(html, "html.parser")
    # Il peut y avoir plusieurs balises generator (WordPress, Elementor, Yoast…) : on les garde toutes
    generators = [m.get("content") or "" for m in soupe.find_all("meta", attrs={"name": re.compile("^generator$", re.I)})]
    cms, gamme = detecter_cms(html, accueil["entetes"], " | ".join(generators))
    motif_generator = (EMPREINTES["cms"].get(cms) or {}).get("generator")
    generator = next((g for g in generators if motif_generator and re.search(motif_generator, g, re.I)), "")

    analyse = {"cms": cms, "gamme": gamme, "version": "", "theme": "", "page_builder": "",
               "https": accueil["url_finale"].startswith("https://") and not accueil["ssl_invalide"],
               "mobile": soupe.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None,
               "copyright": annee_copyright(soupe.get_text(" ")),
               "jquery": "", "flash": False, "tableaux": False,
               "title": bool(soupe.title and soupe.title.get_text(strip=True)),
               "meta_description": soupe.find("meta", attrs={"name": re.compile("^description$", re.I)}) is not None,
               "temps_reponse": accueil["duree"], "pagespeed": None,
               "rdv_en_ligne": "", "formulaire": False, "email": ""}

    if cms == "WordPress":
        analyse["theme"], builders, version_assets = details_wordpress(html)
        analyse["page_builder"] = ", ".join(builders)
        analyse["version"] = _version(generator) or version_assets
    else:
        analyse["version"] = _version(generator) if generator else ""

    jquery = re.search(r"jquery[.-]?(\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js|jquery(?:\.min)?\.js\?ver=(\d+\.\d+(?:\.\d+)?)", html, re.I)
    if jquery:
        analyse["jquery"] = jquery.group(1) or jquery.group(2)
    analyse["flash"] = bool(re.search(r"\.swf\b|x-shockwave-flash", html, re.I))
    analyse["tableaux"] = bool(re.search(r"<td[^>]*>\s*<table", html, re.I)) or \
        (html.lower().count("<table") >= 3 and html.lower().count("<div") < 10)

    texte_complet = (html + " " + html_mentions).lower()
    analyse["rdv_en_ligne"] = ", ".join(nom for nom, motifs in EMPREINTES["rendez_vous"].items()
                                        if any(m.lower() in texte_complet for m in motifs))
    analyse["formulaire"] = any(f.find("textarea") or f.find("input", attrs={"type": "email"})
                                for f in soupe.find_all("form"))
    domaine_site = (urlparse(accueil["url_finale"]).hostname or "").removeprefix("www.")
    analyse["email"] = ", ".join(emails(html + " " + html_mentions, domaine_site)[:2])

    if avec_pagespeed:
        analyse["pagespeed"] = score_pagespeed(accueil["url_finale"])
    analyse["signaux"] = signaux_dates(analyse)
    return analyse


def signaux_dates(analyse):
    """Liste des signaux de site daté (les clés correspondent à score.signaux dans config.yaml)."""
    regles = CONFIG["date"]
    signaux = []
    if not analyse["https"]:
        signaux.append("pas_https")
    if not analyse["mobile"]:
        signaux.append("pas_mobile")
    if analyse["copyright"] and analyse["copyright"] < date.today().year - regles["copyright_ancien_annees"]:
        signaux.append("copyright_ancien")
    if _version_inferieure(analyse["jquery"], regles["jquery_ancien_avant"]):
        signaux.append("jquery_ancien")
    if analyse["flash"]:
        signaux.append("flash")
    if analyse["tableaux"]:
        signaux.append("tableaux")
    if not analyse["title"]:
        signaux.append("pas_de_title")
    if not analyse["meta_description"]:
        signaux.append("pas_de_meta_description")
    if analyse["temps_reponse"] and analyse["temps_reponse"] > regles["temps_reponse_lent"]:
        signaux.append("lent")
    if analyse["pagespeed"] is not None and analyse["pagespeed"] < regles["pagespeed_mauvais"]:
        signaux.append("pagespeed_mauvais")
    return signaux
