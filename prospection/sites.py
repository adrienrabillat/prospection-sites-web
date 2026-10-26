"""Étape 2 — Trouver le site de chaque entreprise et vérifier qu'il est bien le sien.

Ordre : 1) Google Maps via SerpAPI (si clé)  2) devinette de domaine  3) Brave Search (si clé).
Un site n'est retenu que si sa page d'accueil ou ses mentions légales contiennent
le SIREN/SIRET (confiance forte), le téléphone (moyenne) ou le nom + le code postal (faible).
"""

import math
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import cache
from .config import ACTIVITES, CONFIG, EMPREINTES, cle
from .entreprises import LIBELLES_NAF
from .outils import FORMES_JURIDIQUES, mots_utiles, normaliser, telephone_national
from .reseau import ErreurAPI, appel_api, dns_existe, telecharger_page

RESEAUX_SOCIAUX = ("facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee")
TAILLE_HTML_CACHE = 400_000

# Mots trop génériques pour prouver qu'un site appartient à une entreprise (« auto », « ecole »…)
MOTS_GENERIQUES = set()
for _texte in list(ACTIVITES) + list(LIBELLES_NAF.values()):
    MOTS_GENERIQUES.update(normaliser(_texte).split())
MOTS_GENERIQUES.update({"auto", "moto", "ecole", "conduite", "permis", "formation", "france", "paris",
                        "services", "service", "groupe", "holding", "developpement", "academy", "academie"})


# --- Pages web (avec cache par URL) -------------------------------------------------------------

def page(url):
    resultat = cache.lire("urls", url)
    if resultat is None:
        resultat = telecharger_page(url)
        html = resultat["html"]
        a_stocker = resultat
        if len(html) > TAILLE_HTML_CACHE:  # en cache : le début et la fin (le SIRET est souvent en pied de page)
            moitie = TAILLE_HTML_CACHE // 2
            a_stocker = {**resultat, "html": html[:moitie] + "\n<!-- … -->\n" + html[-moitie:]}
        cache.ecrire("urls", url, a_stocker)
    return resultat  # la page complète est utilisée pour l'analyse en cours


def domaine_existe(domaine):
    resultat = cache.lire("urls", f"dns:{domaine}")
    if resultat is None:
        resultat = dns_existe(domaine)
        cache.ecrire("urls", f"dns:{domaine}", resultat)
    return resultat


def domaine_de(url):
    hote = (urlparse(url if "//" in url else "http://" + url).hostname or "").lower()
    return hote.removeprefix("www.")


def est_reseau_social(url):
    return any(domaine_de(url) == d or domaine_de(url).endswith("." + d) for d in RESEAUX_SOCIAUX)


def est_annuaire(url):
    domaine = domaine_de(url)
    return any(domaine == a or domaine.endswith("." + a) for a in CONFIG["annuaires"])


def titre_page(accueil):
    """Contenu de la balise <title> d'une page téléchargée (ou chaîne vide)."""
    if not accueil or not accueil.get("html"):
        return ""
    trouve = re.search(r"<title[^>]*>(.*?)</title>", accueil["html"][:200_000], re.S | re.I)
    return trouve.group(1).strip() if trouve else ""


def texte_visible(html):
    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe(["script", "style", "noscript"]):
        balise.decompose()
    return soupe.get_text(" ")


# --- Validation -------------------------------------------------------------------------------

def _chiffres_colles(texte):
    """Recolle les chiffres séparés par des espaces, points ou tirets (« 123 456 789 » -> « 123456789 »)."""
    return re.sub(r"(?<=\d)[\s.  -]+(?=\d)", "", texte)


def preuve(html, fiche, telephone=None):
    """Cherche dans une page la preuve qu'elle appartient à l'entreprise. Renvoie (confiance, preuve) ou None."""
    texte = texte_visible(html)
    colles = _chiffres_colles(texte + " " + html)
    if re.search(rf"(?<!\d){fiche['siren']}", colles):
        return "fort", "SIREN/SIRET présent"
    numero = telephone_national(telephone or "")
    if numero and re.search(rf"(?:(?<!\d)0|33\(?0?\)?){numero[1:]}(?!\d)", colles):
        return "moyen", "téléphone présent"
    page_normalisee = f" {normaliser(texte)} "
    if fiche["code_postal"] and fiche["code_postal"] in colles:
        for nom in (fiche["enseigne"], fiche["nom"]):
            mots = mots_utiles(nom)
            distinctifs = [m for m in mots if len(m) >= 3 and m not in MOTS_GENERIQUES]
            if distinctifs and all(f" {m} " in page_normalisee for m in mots):
                return "faible", "nom + code postal présents"
    return None


def _liens_mentions(html, url_base):
    """Liens vers les mentions légales (puis contact) du même site."""
    soupe = BeautifulSoup(html, "html.parser")
    mentions, autres = [], []
    for lien in soupe.find_all("a", href=True):
        cible = urljoin(url_base, lien["href"])
        if domaine_de(cible) != domaine_de(url_base):
            continue
        indice = normaliser(lien["href"] + " " + lien.get_text())
        if re.search(r"mention|legal|cgv|cgu|conditions generales", indice):
            mentions.append(cible)
        elif re.search(r"contact|a propos|qui sommes", indice):
            autres.append(cible)
    return list(dict.fromkeys(mentions + autres))[:2]


def valider(accueil, fiche, telephone=None):
    """Cherche la preuve sur l'accueil puis sur les mentions légales. Renvoie (confiance, preuve, html_mentions)."""
    resultat = preuve(accueil["html"], fiche, telephone)
    if resultat:
        return *resultat, ""
    for lien in _liens_mentions(accueil["html"], accueil["url_finale"]):
        mentions = page(lien)
        if mentions["ok"]:
            resultat = preuve(mentions["html"], fiche, telephone)
            if resultat:
                return resultat[0], resultat[1] + " (mentions légales / contact)", mentions["html"]
    return None, None, ""


# --- 1. Google Maps via SerpAPI ---------------------------------------------------------------

def _ressemble(titre, fiche):
    """Le titre (Google, OpenStreetMap…) désigne-t-il la même entreprise que le nom ou l'enseigne ?

    Il faut au moins un mot distinctif commun (pas « auto », « école »…) et des noms proches dans l'ensemble
    (indice de Jaccard ≥ 0,5), sans compter le nom de la ville.
    Exemple rejeté : « Crèche familiale Palloy » pour « Palloy Conduite » (seul le nom de rue est commun).
    """
    ville = set(mots_utiles(fiche["ville"])) | {"garenne"}  # Clichy-la-Garenne
    mots_titre = set(mots_utiles(titre)) - ville
    for nom in (fiche["enseigne"], fiche["nom"]):
        mots = set(mots_utiles(nom)) - ville
        if not mots or not mots_titre:
            continue
        communs = mots & mots_titre
        distinctifs = {m for m in mots if m not in MOTS_GENERIQUES and len(m) >= 3}
        jaccard = len(communs) / len(mots | mots_titre)
        if distinctifs and communs & distinctifs and jaccard >= 0.5:
            return True
        if not distinctifs and mots == mots_titre:  # nom entièrement générique : il faut l'identique
            return True
    return False


def appel_serpapi(requete):
    """Appel SerpAPI Google Maps, mis en cache et compté. Renvoie None si quota atteint ou pas de clé."""
    cle_api = cle("SERPAPI_KEY")
    if not cle_api:
        return None
    reponse = cache.lire("api", f"serpapi:{requete}")
    if reponse is not None:
        return reponse
    if cache.compteur("serpapi") >= CONFIG["serpapi"]["plafond_mensuel"]:
        print("    ⚠️  Plafond SerpAPI du mois atteint : Google Maps ignoré")
        return None
    try:
        reponse = appel_api("https://serpapi.com/search.json", {
            "engine": "google_maps", "type": "search", "q": requete,
            "hl": "fr", "gl": "fr", "google_domain": "google.fr", "api_key": cle_api})
    except ErreurAPI as erreur:
        print(f"    ⚠️  SerpAPI : {str(erreur).replace(cle_api, '***')}")
        return None
    cache.incrementer("serpapi")
    cache.ecrire("api", f"serpapi:{requete}", reponse)
    return reponse


def chercher_google_maps(fiche):
    nom = fiche["enseigne"] or fiche["nom"]
    reponse = appel_serpapi(f"{nom} {fiche['code_postal']} {fiche['ville']}")
    if not reponse:
        return None
    lieux = [reponse["place_results"]] if reponse.get("place_results") else reponse.get("local_results", [])
    for lieu in lieux[:5]:
        adresse = normaliser(lieu.get("address", ""))
        bonne_ville = fiche["code_postal"] in adresse or normaliser(fiche["ville"]) in adresse
        if _ressemble(lieu.get("title", ""), fiche) and bonne_ville:
            return {"url": lieu.get("website"), "telephone": lieu.get("phone"), "note": lieu.get("rating"),
                    "nb_avis": lieu.get("reviews"), "titre_google": lieu.get("title")}
    return {}  # recherche faite, aucune fiche correspondante


# --- 1 bis. OpenStreetMap (gratuit, sans clé) -------------------------------------------------

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
RAYON_OSM = 150  # mètres autour de l'adresse de l'établissement


def _distance_m(lat1, lon1, lat2, lon2):
    """Distance approximative en mètres (suffisant à l'échelle d'une rue), infinie si une coordonnée manque."""
    try:
        dx = (float(lon2) - float(lon1)) * 111_320 * math.cos(math.radians(float(lat1)))
        dy = (float(lat2) - float(lat1)) * 110_540
    except (TypeError, ValueError):
        return math.inf
    return math.hypot(dx, dy)


def prechercher_openstreetmap(fiches, par_lot=25):
    """Interroge OpenStreetMap (API Overpass, gratuite) en une requête par lot de 25 entreprises.

    Le serveur public est lent (souvent 30 s par requête) : grouper évite d'en faire une par entreprise.
    Le résultat de chaque entreprise est mis en cache sous la clé « osm:<SIREN> ».
    """
    a_chercher = [f for f in fiches if f.get("latitude") and f.get("longitude")
                  and cache.lire("api", f"osm:{f['siren']}") is None]
    for debut in range(0, len(a_chercher), par_lot):
        lot = a_chercher[debut:debut + par_lot]
        filtres = "".join(f'nwr(around:{RAYON_OSM},{f["latitude"]},{f["longitude"]})[name]'
                          f'[~"^(shop|amenity|office|craft|healthcare|leisure|tourism)$"~"."];' for f in lot)
        print(f"  🗺️  OpenStreetMap : lot de {len(lot)} entreprises…")
        try:
            reponse = appel_api(URL_OVERPASS, donnees={"data": f"[out:json][timeout:90];({filtres});out tags center;"},
                                timeout=120, tentatives=3)
        except ErreurAPI as erreur:
            print(f"    ⚠️  OpenStreetMap indisponible : {erreur}")
            return
        for fiche in lot:  # on garde, pour chaque entreprise, les lieux nommés proches de son adresse
            proches = []
            for element in reponse.get("elements", []):
                lat = element.get("lat") or (element.get("center") or {}).get("lat")
                lon = element.get("lon") or (element.get("center") or {}).get("lon")
                if lat is not None and _distance_m(fiche["latitude"], fiche["longitude"], lat, lon) <= RAYON_OSM:
                    proches.append(element.get("tags", {}))
            cache.ecrire("api", f"osm:{fiche['siren']}", proches)


def chercher_openstreetmap(fiche):
    """Lieu OpenStreetMap du même nom près de l'adresse : dict (vide si aucun), ou None si non interrogé."""
    proches = cache.lire("api", f"osm:{fiche['siren']}")
    if proches is None:
        return None
    for tags in proches:
        if _ressemble(tags.get("name", ""), fiche):
            url = tags.get("website") or tags.get("contact:website") or tags.get("url")
            reseau = tags.get("contact:facebook") or tags.get("contact:instagram") or tags.get("facebook")
            if reseau and not reseau.startswith("http"):
                reseau = f"https://www.facebook.com/{reseau}"
            return {"url": url or reseau, "telephone": tags.get("phone") or tags.get("contact:phone"),
                    "nom_osm": tags.get("name")}
    return {}


# --- 2. Devinette de domaine ------------------------------------------------------------------

def _coller_generiques(mots):
    """Colle les mots génériques qui se suivent : [ask, auto, ecole] -> [ask, autoecole] (pour « ask-autoecole »)."""
    groupes = []
    for mot in mots:
        if groupes and mot in MOTS_GENERIQUES and groupes[-1][-1] in MOTS_GENERIQUES:
            groupes[-1].append(mot)
        else:
            groupes.append([mot])
    return ["".join(g) for g in groupes]


def domaines_candidats(fiche):
    ville = mots_utiles(fiche["ville"])
    candidats = []
    for nom in dict.fromkeys(n for n in (fiche["enseigne"], fiche["nom"]) if n):
        mots = mots_utiles(nom)
        if not mots:
            continue
        avec_articles = [m for m in normaliser(nom).split() if m not in FORMES_JURIDIQUES]  # « de-la-reussite »
        sans_ville = [m for m in mots if m not in ville]  # « newton » pour « Auto-École Newton Levallois »
        colles = _coller_generiques(mots)  # « ask-autoecole »
        variantes = [mots, colles, avec_articles] + ([sans_ville] if sans_ville and sans_ville != mots else [])
        if ville and not set(ville) <= set(mots):
            variantes.append(mots + ville)
        for variante in dict.fromkeys(map(tuple, variantes)):
            for separateur in ("", "-"):
                for extension in CONFIG["devinette"]["extensions"]:
                    etiquette = separateur.join(variante)
                    if 3 <= len(etiquette) <= 63:
                        candidats.append(f"{etiquette}.{extension}")
    return list(dict.fromkeys(candidats))[:CONFIG["devinette"]["max_domaines"]]


def deviner_domaine(fiche, telephone=None):
    for domaine in domaines_candidats(fiche):
        if not domaine_existe(domaine):
            continue
        for url in (f"https://{domaine}", f"http://{domaine}"):
            accueil = page(url)
            if accueil["ok"]:
                confiance, motif, html_mentions = valider(accueil, fiche, telephone)
                if confiance:
                    return accueil, confiance, motif, html_mentions
                break
    return None


# --- 3. Brave Search --------------------------------------------------------------------------

def appel_brave(requete):
    cle_api = cle("BRAVE_API_KEY")
    if not cle_api:
        return None
    reponse = cache.lire("api", f"brave:{requete}")
    if reponse is not None:
        return reponse
    if cache.compteur("brave") >= CONFIG["brave"]["plafond_mensuel"]:
        print("    ⚠️  Plafond Brave du mois atteint : recherche web ignorée")
        return None
    try:
        reponse = appel_api("https://api.search.brave.com/res/v1/web/search",
                            {"q": requete, "country": "fr", "search_lang": "fr", "count": 10},
                            entetes={"Accept": "application/json", "X-Subscription-Token": cle_api})
    except ErreurAPI as erreur:
        print(f"    ⚠️  Brave : {erreur}")
        return None
    cache.incrementer("brave")
    cache.ecrire("api", f"brave:{requete}", reponse)
    return reponse


def chercher_brave(fiche, telephone=None):
    """Renvoie (accueil, confiance, preuve, html_mentions) d'un site validé, ou une URL de réseau social."""
    nom = fiche["enseigne"] or fiche["nom"]
    reponse = appel_brave(f'"{nom}" {fiche["ville"]}')
    if not reponse:
        return None, None
    resultats = (reponse.get("web") or {}).get("results", [])
    reseau_social, testes = None, set()
    for resultat in resultats:
        url = resultat.get("url", "")
        if est_reseau_social(url) and not reseau_social and _ressemble(resultat.get("title", ""), fiche):
            reseau_social = url
        if est_annuaire(url) or domaine_de(url) in testes or len(testes) >= 3:
            continue
        testes.add(domaine_de(url))
        accueil = page(f"{urlparse(url).scheme}://{urlparse(url).netloc}/")
        if accueil["ok"]:
            confiance, motif, html_mentions = valider(accueil, fiche, telephone)
            if confiance:
                return (accueil, confiance, motif, html_mentions), None
    return None, reseau_social


# --- Synthèse ---------------------------------------------------------------------------------

def _contient(html, motifs):
    html = html.lower()
    return any(m.lower() in html for m in motifs)


def statut_url(accueil):
    """Statut web d'une URL donnée par une source sûre (fiche Google)."""
    if accueil["erreur"] == "DNS":
        return "Domaine expiré / DNS absent"
    if est_reseau_social(accueil["url_finale"]):
        return "Facebook / Instagram seulement"
    entetes = accueil["entetes"]
    if accueil["statut"] in (401, 403) and ("cloudflare" in entetes.get("server", "") or "cf-ray" in entetes):
        return "Site actif"  # protection anti-robots : le site existe
    if not accueil["ok"]:
        return f"Site cassé ({'HTTP ' + str(accueil['statut']) if accueil['statut'] else accueil['erreur']})"
    if _contient(accueil["html"], EMPREINTES["pages_parking"]):
        return "Domaine expiré / DNS absent"
    page_vide = "<script" not in accueil["html"].lower() and len(texte_visible(accueil["html"]).split()) < 15
    if page_vide or _contient(accueil["html"], EMPREINTES["pages_par_defaut"]):
        return "Site cassé (page vide ou par défaut)"
    return "Site actif"


def _depuis_fiche(resultat, url, source, fiche, telephone):
    """URL indiquée sur une fiche (Google, OpenStreetMap) déjà associée à l'entreprise."""
    resultat.update(url=url, source=source)
    if est_reseau_social(url):
        resultat.update(statut="Facebook / Instagram seulement", confiance="moyen", preuve=f"lien de la fiche {source}")
        return resultat
    accueil = page(url)
    resultat["accueil"] = accueil
    resultat["statut"] = statut_url(accueil)
    if resultat["statut"] != "Site actif" or not accueil["ok"]:
        resultat.update(confiance="moyen", preuve=f"lien de la fiche {source}")
        return resultat
    confiance, motif, html_mentions = valider(accueil, fiche, telephone)
    # La fiche pointe vers ce site : même sans preuve dans la page, on le garde (confiance faible).
    resultat.update(confiance=confiance or "faible", preuve=motif or f"lien de la fiche {source} seulement",
                    html_mentions=html_mentions)
    return resultat


def trouver_site(fiche, avec_serpapi=True, avec_brave=True):
    """Renvoie un dict : statut, url, source, confiance, preuve, google{…}, accueil, html_mentions."""
    resultat = {"statut": "Aucun site", "url": "", "source": "", "confiance": "", "preuve": "",
                "google": {}, "telephone": "", "accueil": None, "html_mentions": "", "methodes": []}

    # 1. Google Maps
    google = chercher_google_maps(fiche) if avec_serpapi else None
    if google is not None:
        resultat["methodes"].append("Google Maps")
        resultat["google"] = {k: v for k, v in google.items() if k != "url"}
    telephone = (google or {}).get("telephone")
    if google and google.get("url"):
        resultat["telephone"] = telephone
        return _depuis_fiche(resultat, google["url"], "Google Maps", fiche, telephone)

    # 1 bis. OpenStreetMap
    osm = chercher_openstreetmap(fiche)
    if osm is not None:
        resultat["methodes"].append("OpenStreetMap")
    telephone = telephone or (osm or {}).get("telephone")
    resultat["telephone"] = telephone or ""
    if osm and osm.get("url"):
        return _depuis_fiche(resultat, osm["url"], "OpenStreetMap", fiche, telephone)

    # 2. Devinette de domaine
    resultat["methodes"].append("devinette")
    trouve = deviner_domaine(fiche, telephone)
    source = "Devinette de domaine"

    # 3. Brave Search
    reseau_social = None
    if not trouve and avec_brave and cle("BRAVE_API_KEY"):
        resultat["methodes"].append("Brave")
        trouve, reseau_social = chercher_brave(fiche, telephone)
        source = "Brave Search"

    if trouve:
        accueil, confiance, motif, html_mentions = trouve
        resultat.update(url=accueil["url_finale"], source=source, confiance=confiance, preuve=motif,
                        accueil=accueil, html_mentions=html_mentions, statut=statut_url(accueil))
    elif reseau_social:
        resultat.update(statut="Facebook / Instagram seulement", url=reseau_social, source="Brave Search",
                        confiance="faible", preuve="titre du résultat proche du nom")
    else:
        # Plus on a cherché, plus « Aucun site » est fiable
        resultat["confiance"] = "moyen" if len(resultat["methodes"]) > 1 else "faible"
        resultat["preuve"] = "rien trouvé via : " + ", ".join(resultat["methodes"])
    return resultat
