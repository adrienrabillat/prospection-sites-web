"""Étape 2 — Visiter chaque site comme un vrai visiteur, dans un navigateur (Chromium sans fenêtre).

Pour chaque site : une capture d'écran sur ordinateur, une sur mobile, le texte affiché, et des indices
techniques (constructeur de site, adaptation mobile, année du copyright, coordonnées…).
Le chargement sur mobile est mesuré (temps d'affichage, poids, requêtes) et passé au référentiel d'audit.py
(performance, SEO, GEO). Au plus quatre pages par site (l'accueil sur ordinateur et sur mobile, les mentions
légales, la page contact), plus robots.txt, sitemap.xml et llms.txt.
"""

import asyncio
import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Error as ErreurNavigateur
from playwright.async_api import async_playwright

from .audit import auditer
from .config import CONFIG, DOSSIER_DATA, EMPREINTES
from .outils import slug, telephone_national

REGLES = CONFIG["visite"]
ECRAN = {"width": 1280, "height": 1400}
MOBILE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
          "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"}
ACCEPTER = re.compile(r"^\s*(tout accepter|accepter( et fermer| tout| les cookies)?|j.accepte|ok( pour moi)?|"
                      r"accept( all)?|autoriser( tout)?|d.accord)\s*$", re.I)
# Adresses offertes par les constructeurs de sites gratuits : signe presque certain d'un site fait soi-même
SOUS_DOMAINES_GRATUITS = ("wixsite.com", "jimdofree.com", "jimdosite.com", "jimdo.com", "e-monsite.com",
                          "wordpress.com", "blogspot.com", "blogspot.fr", "sites.google.com", "webnode.fr",
                          "webnode.page", "site123.me", "weebly.com", "pagesperso-orange.fr", "free.fr",
                          "over-blog.com", "canalblog.com", "sitew.fr", "sitew.com", "wifeo.com", "eatbu.com",
                          "godaddysites.com", "ueniweb.com", "strikingly.com", "mystrikingly.com", "yolasite.com",
                          "simplesite.com", "webself.net", "cmonsite.fr", "square.site", "odoo.com", "carrd.co")
WEBMAILS = ("gmail.com", "hotmail.fr", "hotmail.com", "outlook.fr", "outlook.com", "live.fr", "yahoo.fr", "yahoo.com",
            "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "neuf.fr", "laposte.net", "icloud.com", "bbox.fr", "aol.com")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
EMAILS_IGNORES = ("example.", "sentry", "wixpress", "domain.", "email.com", "votre", "nom@", "@2x", ".png", ".jpg",
                  ".webp", ".gif", ".svg")
TELEPHONE = re.compile(r"(?:(?:\+|00)33[\s.-]?\(?0?\)?[\s.-]?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}")
SIRET = re.compile(r"(?:siret|siren|rcs)[^\d]{0,40}(\d{3}[\s.]?\d{3}[\s.]?\d{3}(?:[\s.]?\d{5})?)", re.I)
REALISATION = re.compile(r"((?:site|création|conception|réalisation)[^.<>\n]{0,25}"
                         r"(?:réalisé|créé|conçu|développé|propulsé|hébergé)?\s*(?:par|by|:)\s*[^.<>\n|]{2,50})", re.I)
RESEAU_4G = {"latency": 150, "downloadThroughput": 1.6e6 / 8, "uploadThroughput": 750e3 / 8}  # réglages Lighthouse
BLOCAGES = (401, 403, 418, 429, 503)  # protection anti-robot ou surcharge : le site existe peut-être, à voir à la main


def dossier_captures(ville):
    dossier = DOSSIER_DATA / slug(ville) / "captures"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _motif_erreur(erreur):
    texte = str(erreur)
    for code, motif in (("ERR_NAME_NOT_RESOLVED", "domaine introuvable (DNS)"),
                        ("ERR_CONNECTION", "connexion impossible"), ("ERR_CERT", "certificat de sécurité invalide"),
                        ("ERR_SSL", "erreur de sécurité (SSL)"), ("Timeout", "délai dépassé"),
                        ("ERR_TOO_MANY_REDIRECTS", "boucle de redirections"), ("ERR_EMPTY_RESPONSE", "réponse vide")):
        if code in texte:
            return motif
    return texte.splitlines()[0][:80]


MESURE = """
window.__lcp = null; window.__cls = 0;
try {
  new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = e.startTime })
    .observe({type: 'largest-contentful-paint', buffered: true});
  new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value })
    .observe({type: 'layout-shift', buffered: true});
} catch (e) {}
"""
LIRE_MESURE = """() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  return {lcp: window.__lcp, cls: window.__cls, ttfb: n.responseStart || null, charge: n.loadEventEnd || null};
}"""


async def _ouvrir(page, url):
    """Ouvre la page, attend qu'elle soit chargée, relève les temps de chargement et ferme le bandeau de cookies.

    Renvoie (réponse, mesures brutes en millisecondes).
    """
    reponse = await page.goto(url, wait_until="domcontentloaded", timeout=REGLES["delai_chargement_s"] * 1000)
    try:
        await page.wait_for_load_state("load", timeout=12_000)
    except ErreurNavigateur:
        pass  # des ressources traînent : on prend la page telle qu'un visiteur la verrait après 12 s
    await page.wait_for_timeout(1500)
    try:
        mesures = await page.evaluate(LIRE_MESURE)
    except ErreurNavigateur:
        mesures = {}
    for role in ("button", "link"):
        try:
            await page.get_by_role(role, name=ACCEPTER).first.click(timeout=800)
            await page.wait_for_timeout(600)
            break
        except ErreurNavigateur:
            pass
    return reponse, mesures


async def _fichiers(contexte, url_finale):
    """robots.txt, sitemap.xml et llms.txt du site (trois petites requêtes)."""
    racine = "{0.scheme}://{0.netloc}".format(urlparse(url_finale))
    contenus = {}
    for nom in ("robots.txt", "sitemap.xml", "llms.txt"):
        try:
            reponse = await contexte.request.get(f"{racine}/{nom}", timeout=10_000)
            texte = (await reponse.text())[:20_000] if reponse.ok else None
        except (ErreurNavigateur, UnicodeDecodeError):
            texte = None
        contenus[nom] = None if texte is None or "<html" in texte[:500].lower() else texte  # page d'erreur déguisée
    robots = contenus["robots.txt"]
    return {"robots": robots, "llms": bool(contenus["llms.txt"]),
            "sitemap": bool(contenus["sitemap.xml"] and "<" in contenus["sitemap.xml"][:200])
            or "sitemap:" in (robots or "").lower()}


def indices(html, texte, url_finale, entetes):
    """Indices techniques relevés sur la page d'accueil (aucune requête de plus)."""
    soupe = BeautifulSoup(html, "html.parser")
    html_min = html.lower()
    generators = " | ".join(m.get("content") or "" for m in
                            soupe.find_all("meta", attrs={"name": re.compile("^generator$", re.I)}))
    constructeur, gamme = "", ""
    for nom, regles in EMPREINTES["cms"].items():
        if any(m.lower() in html_min for m in regles.get("html", [])) \
                or any(e.startswith(p) for p in regles.get("entetes", []) for e in entetes) \
                or (regles.get("generator") and re.search(regles["generator"], generators, re.I)):
            constructeur, gamme = nom, regles.get("gamme", "standard")
            break
    domaine = (urlparse(url_finale).hostname or "").removeprefix("www.")
    annees = [int(a) for a in re.findall(r"(?:©|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", texte, re.I)]
    realisation = REALISATION.search(soupe.get_text(" ")[-3000:])
    adresses = [e.lower() for e in EMAIL.findall(html) if not any(i in e.lower() for i in EMAILS_IGNORES)]
    return {
        "constructeur": constructeur, "gamme": gamme, "generator": generators[:120],
        "https": url_finale.startswith("https://"),
        "balise_mobile": soupe.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None,
        "copyright": max(annees) if annees and max(annees) <= date.today().year else None,
        "adresse_gratuite": next((s for s in SOUS_DOMAINES_GRATUITS if domaine.endswith("." + s)), ""),
        "mise_en_page_tableaux": len(soupe.find_all("table")) >= 3 and not soupe.find(["main", "section", "article"]),
        "flash_ou_frames": bool(soupe.find(["frameset", "frame", "marquee"]) or ".swf" in html_min),
        "lorem_ipsum": "lorem ipsum" in texte.lower(),
        "email_grand_public": any(a.split("@")[1] in WEBMAILS for a in adresses),
        "realisation": " ".join(realisation.group(1).split())[:90] if realisation else "",
        "nb_mots": len(texte.split()),
        "nb_images": len(soupe.find_all("img")),
        "titre": (soupe.title.get_text(" ", strip=True) if soupe.title else "")[:150],
    }


def coordonnees(textes, html, domaine):
    """E-mails, téléphones et SIRET relevés dans le texte affiché des pages lues (et les liens tel: / mailto:)."""
    tout = "\n".join(textes)
    emails = []
    for adresse in (e.lower().strip(".") for e in EMAIL.findall(tout + "\n" + html)):
        d = adresse.split("@")[1]
        if not any(i in adresse for i in EMAILS_IGNORES) and (d in WEBMAILS or d == domaine or domaine.endswith("." + d)):
            emails.append(adresse)
    # Jamais dans le HTML brut : il est plein de suites de chiffres qui ressemblent à des numéros
    telephones = [telephone_national(t) for t in re.findall(r"tel:([+\d\s.()-]{9,20})", html) + TELEPHONE.findall(tout)]
    siret = SIRET.search(tout)
    return {"emails": list(dict.fromkeys(emails))[:3],
            "telephones": list(dict.fromkeys(t for t in telephones if t))[:3],
            "siret": re.sub(r"\D", "", siret.group(1)) if siret else ""}


def _liens_utiles(html, url_finale):
    """Liens vers les mentions légales et la page contact du même site (un de chaque au plus)."""
    trouves = {}
    hote = urlparse(url_finale).hostname
    for lien in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        cible = urljoin(url_finale, lien["href"]).split("#")[0]
        libelle = f"{lien['href']} {lien.get_text(' ')}".lower()
        if urlparse(cible).hostname != hote or not cible.startswith("http"):
            continue
        for sorte, motif in (("mentions", r"mentions|legal"), ("contact", r"contact")):
            if sorte not in trouves and re.search(motif, libelle) and cible.rstrip("/") != url_finale.rstrip("/"):
                trouves[sorte] = cible
    return list(trouves.values())


async def _visiter(navigateur, candidat, dossier):
    """Visite un site. Renvoie le compte rendu : état « ok », « cassé » ou « bloqué », captures, texte, indices."""
    nom_fichier = slug(candidat["cle"])[:80]
    visite = {"date": date.today().isoformat(), "etat": "ok", "motif": "", "url_finale": candidat["url"]}
    contexte = await navigateur.new_context(viewport=ECRAN, locale="fr-FR", ignore_https_errors=True)
    try:
        page = await contexte.new_page()
        reponse = None
        for essai in range(2):  # une panne passagère ne doit pas faire croire à un site cassé
            try:
                reponse, _ = await _ouvrir(page, candidat["url"])
                break
            except ErreurNavigateur as erreur:
                visite.update(etat="cassé", motif=_motif_erreur(erreur))
                await asyncio.sleep(3)
        else:
            return visite
        statut = reponse.status if reponse else 200
        parties = urlparse(candidat["url"])
        if statut >= 500 and statut not in BLOCAGES:  # panne passagère du serveur : un second essai
            await asyncio.sleep(5)
        elif statut in (404, 410) and parties.path not in ("", "/"):
            # Le lien donné par Google ou OpenStreetMap pointe sur une page disparue : on regarde l'accueil du site
            candidat = {**candidat, "url": f"{parties.scheme}://{parties.netloc}/"}
            visite["lien_casse"] = True
        if statut >= 500 and statut not in BLOCAGES or visite.get("lien_casse"):
            try:
                reponse, _ = await _ouvrir(page, candidat["url"])
                statut = reponse.status if reponse else 200
            except ErreurNavigateur as erreur:
                return {**visite, "etat": "cassé", "motif": _motif_erreur(erreur)}
        html = await page.content()
        try:
            html_brut = await reponse.text() if reponse else html  # le code reçu, avant tout JavaScript
        except ErreurNavigateur:
            html_brut = html
        texte = await page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        visite.update(etat="ok", motif="", url_finale=page.url, statut_http=statut)
        if statut in BLOCAGES:
            return {**visite, "etat": "bloqué", "motif": f"HTTP {statut} (protection anti-robot ou surcharge)"}
        if statut >= 400:
            return {**visite, "etat": "cassé", "motif": f"erreur HTTP {statut}"}
        html_min = html.lower()
        if any(m in html_min for m in EMPREINTES["pages_parking"]):
            return {**visite, "etat": "cassé", "motif": "domaine expiré, parqué ou à vendre"}
        visite["page_par_defaut"] = next((m for m in EMPREINTES["pages_par_defaut"] if m in html_min), "")

        visite["capture_ordinateur"] = f"captures/{nom_fichier}.jpg"
        await page.screenshot(path=dossier / f"{nom_fichier}.jpg", type="jpeg", quality=70)
        entetes = [k.lower() for k in (reponse.headers if reponse else {})]
        visite["indices"] = indices(html, texte, page.url, entetes)
        visite["texte"] = re.sub(r"\n\s*\n+", "\n", texte).strip()[:5000]

        textes = [texte]
        for lien in _liens_utiles(html, page.url):
            try:
                autre = await contexte.request.get(lien, timeout=15_000)
                if autre.ok:
                    textes.append(BeautifulSoup(await autre.text(), "html.parser").get_text(" "))
            except (ErreurNavigateur, UnicodeDecodeError):
                pass
        visite["coordonnees"] = coordonnees(textes, html, (urlparse(page.url).hostname or "").removeprefix("www."))
        fichiers = await _fichiers(contexte, page.url)
    finally:
        await contexte.close()

    # Version mobile : capture, et mesure du chargement (c'est sur mobile que Google évalue la vitesse)
    mesures, reseau = {}, {"octets": 0, "requetes": 0}
    contexte = await navigateur.new_context(**MOBILE, locale="fr-FR", ignore_https_errors=True)
    try:
        await contexte.add_init_script(MESURE)
        page = await contexte.new_page()
        cdp = await contexte.new_cdp_session(page)
        await cdp.send("Network.enable")

        def compter(evenement):
            reseau["octets"] += evenement.get("encodedDataLength", 0)
            reseau["requetes"] += 1

        cdp.on("Network.loadingFinished", compter)
        # Mêmes conditions que le test mobile de Google PageSpeed : 4G lente et processeur quatre fois plus lent
        await cdp.send("Network.emulateNetworkConditions", {**RESEAU_4G, "offline": False})
        await cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        _, brutes = await _ouvrir(page, visite["url_finale"])
        en_secondes = lambda v: round(v / 1000, 1) if v else None  # noqa: E731
        mesures = {"lcp_s": en_secondes(brutes.get("lcp")), "ttfb_s": en_secondes(brutes.get("ttfb")),
                   "chargement_s": en_secondes(brutes.get("charge")),
                   "cls": round(brutes["cls"], 2) if brutes.get("cls") is not None else None,
                   "poids_mo": round(reseau["octets"] / 1e6, 1), "requetes": reseau["requetes"]}
        # Mesure faite : on rend sa vitesse au navigateur pour que la capture montre la page complète
        await cdp.send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
        await cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except ErreurNavigateur:
            pass
        visite["indices"]["deborde_sur_mobile"] = await page.evaluate(
            "() => document.documentElement.scrollWidth > window.innerWidth + 8")
        await page.screenshot(path=dossier / f"{nom_fichier}_mobile.jpg", type="jpeg", quality=70)
        visite["capture_mobile"] = f"captures/{nom_fichier}_mobile.jpg"
    except ErreurNavigateur:
        pass  # la version ordinateur suffit pour juger l'apparence
    finally:
        await contexte.close()
    visite["audit"] = auditer(html, html_brut, texte, visite["url_finale"], candidat["ville"], mesures, fichiers)
    return visite


async def _visiter_tout(candidats, dossier, apres):
    async with async_playwright() as p:
        navigateur = await p.chromium.launch()
        places = asyncio.Semaphore(REGLES["parallele"])

        async def un(candidat):
            async with places:
                try:
                    candidat["visite"] = await asyncio.wait_for(_visiter(navigateur, candidat, dossier), timeout=150)
                except Exception as erreur:  # un site ne doit jamais arrêter les autres
                    candidat["visite"] = {"date": date.today().isoformat(), "etat": "bloqué",
                                          "motif": f"visite impossible ({erreur.__class__.__name__})",
                                          "url_finale": candidat["url"]}
                apres(candidat)

        await asyncio.gather(*(un(c) for c in candidats))
        await navigateur.close()


def visiter(candidats, ville, apres):
    """Visite les sites (plusieurs à la fois) et appelle `apres(candidat)` dès qu'un site est vu."""
    if candidats:
        asyncio.run(_visiter_tout(candidats, dossier_captures(ville), apres))
