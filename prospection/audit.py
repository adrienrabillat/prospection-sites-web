"""Le référentiel : ce qui fait qu'un site est bon ou mauvais, en dehors de son apparence.

Trois notes sur 100, calculées par des règles fixes à partir de ce qui a été mesuré pendant la visite
(aucun avis de l'IA ici, donc le même site obtient toujours la même note) :
- Performance : chargement réel de la page sur mobile dans Chromium (indicateurs Core Web Vitals de Google) ;
- SEO : les bases du référencement naturel, surtout local ;
- GEO : la capacité du site à être lu et cité par les moteurs à IA (ChatGPT, Perplexity, Google AI Overviews…).
La quatrième note, le design, est donnée par Claude sur une grille de six critères (voir jugement.py).

Chaque critère est une ligne (libellé, points gagnés, points possibles, détail) : la note est la somme des points.
Les mesures de performance sont faites dans les conditions du test mobile de Google PageSpeed (4G lente,
processeur ralenti quatre fois) : elles sont comparables d'un site à l'autre, à quelques dixièmes près.
"""

import json
import re

from bs4 import BeautifulSoup

from .outils import normaliser

ROBOTS_IA = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot", "Google-Extended")


def _paliers(valeur, bon, moyen, points):
    """Tous les points sous le seuil « bon », la moitié sous le seuil « moyen », zéro au-delà ou sans mesure."""
    if valeur is None:
        return 0
    return points if valeur <= bon else points // 2 if valeur <= moyen else 0


def _note(criteres):
    return {"note": round(100 * sum(c[1] for c in criteres) / sum(c[2] for c in criteres)),
            "criteres": [{"libelle": c[0], "points": c[1], "sur": c[2], "detail": c[3]} for c in criteres],
            "defauts": [f"{c[0]} : {c[3]}" for c in criteres if c[1] < c[2]]}


# --- Performance ------------------------------------------------------------------------------

def performance(mesures):
    """Seuils de Google pour LCP, CLS et TTFB (bon / à améliorer / mauvais) ; poids et requêtes : usages du métier."""
    m = mesures or {}
    if m.get("lcp_s") is None and not m.get("requetes"):
        return {"note": None, "criteres": [], "defauts": []}  # la version mobile n'a pas pu être chargée
    lcp, cls, ttfb, poids, requetes = (m.get(k) for k in ("lcp_s", "cls", "ttfb_s", "poids_mo", "requetes"))
    texte = lambda v, unite: "non mesuré" if v is None else f"{v} {unite}".strip()  # noqa: E731
    return _note([
        ("Affichage du contenu principal (LCP)", _paliers(lcp, 2.5, 4.0, 40), 40, texte(lcp, "s (bon : 2,5 s au plus)")),
        ("Poids de la page", _paliers(poids, 1.5, 3.0, 20), 20, texte(poids, "Mo (bon : 1,5 Mo au plus)")),
        ("Nombre de requêtes", _paliers(requetes, 60, 120, 10), 10, texte(requetes, "(bon : 60 au plus)")),
        ("Réponse du serveur (TTFB)", _paliers(ttfb, 0.8, 1.8, 15), 15, texte(ttfb, "s (bon : 0,8 s au plus)")),
        ("Stabilité de la mise en page (CLS)", _paliers(cls, 0.1, 0.25, 15), 15, texte(cls, "(bon : 0,1 au plus)")),
    ])


# --- SEO --------------------------------------------------------------------------------------

def seo(soupe, texte, url_finale, ville, fichiers):
    titre = soupe.title.get_text(" ", strip=True) if soupe.title else ""
    description = soupe.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = (description.get("content") or "").strip() if description else ""
    h1 = [h.get_text(" ", strip=True) for h in soupe.find_all("h1")]
    images = soupe.find_all("img")
    avec_alt = sum(1 for i in images if (i.get("alt") or "").strip())
    robots_meta = soupe.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    noindex = bool(robots_meta and "noindex" in (robots_meta.get("content") or "").lower())
    ville_citee = normaliser(ville) in normaliser(f"{titre} {' '.join(h1)}")
    nb_mots = len(texte.split())
    oui = lambda ok, points: points if ok else 0  # noqa: E731
    return _note([
        ("Titre de page", oui(10 <= len(titre) <= 65, 12), 12,
         f"{len(titre)} caractères (attendu : 10 à 65)" if titre else "absent"),
        ("Description pour Google", oui(50 <= len(description) <= 170, 10), 10,
         f"{len(description)} caractères (attendu : 50 à 170)" if description else "absente"),
        ("Un titre principal (H1) unique", oui(len(h1) == 1 and h1[0], 10), 10, f"{len(h1)} balise(s) H1"),
        ("Ville dans le titre ou le H1", oui(ville_citee, 10), 10,
         "oui" if ville_citee else f"« {ville} » n'y figure pas : mauvais pour les recherches locales"),
        ("Contenu suffisant", oui(nb_mots >= 250, 10), 10, f"{nb_mots} mots sur l'accueil (attendu : 250 au moins)"),
        ("HTTPS", oui(url_finale.startswith("https://"), 8), 8,
         "oui" if url_finale.startswith("https://") else "site non sécurisé"),
        ("Adapté au mobile (balise viewport)", oui(soupe.find("meta", attrs={"name": re.compile("^viewport$", re.I)}), 8), 8,
         "oui" if soupe.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) else "absente"),
        ("Textes alternatifs des images", oui(not images or avec_alt / len(images) >= 0.8, 8), 8,
         f"{avec_alt} image(s) décrite(s) sur {len(images)}"),
        ("Indexable par Google", oui(not noindex, 6), 6, "bloqué par une balise noindex" if noindex else "oui"),
        ("Plan du site (sitemap.xml)", oui(fichiers.get("sitemap"), 5), 5, "présent" if fichiers.get("sitemap") else "absent"),
        ("Langue déclarée", oui(soupe.html and soupe.html.get("lang"), 4), 4,
         "oui" if soupe.html and soupe.html.get("lang") else "attribut lang absent"),
        ("Adresse canonique", oui(soupe.find("link", rel="canonical"), 4), 4,
         "oui" if soupe.find("link", rel="canonical") else "absente"),
        ("Fichier robots.txt", oui(fichiers.get("robots") is not None, 3), 3,
         "présent" if fichiers.get("robots") is not None else "absent"),
    ])


# --- GEO (visibilité dans les moteurs à IA) ---------------------------------------------------

def _donnees_structurees(soupe):
    """Types schema.org déclarés en JSON-LD, et présence d'une adresse ou d'un téléphone dans ces données."""
    types, coordonnees = set(), False

    def parcourir(noeud):
        nonlocal coordonnees
        if isinstance(noeud, list):
            for element in noeud:
                parcourir(element)
        elif isinstance(noeud, dict):
            sorte = noeud.get("@type")
            types.update(sorte if isinstance(sorte, list) else [sorte] if sorte else [])
            coordonnees = coordonnees or "address" in noeud or "telephone" in noeud
            for valeur in noeud.values():
                parcourir(valeur)

    for script in soupe.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            parcourir(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            pass
    return {str(t) for t in types}, coordonnees


def _robots_ia_bloques(robots):
    """Robots d'IA interdits de tout le site par robots.txt (règle « Disallow: / » pour eux ou pour tous)."""
    bloques, agents, nouveau_groupe = set(), [], True
    for ligne in (robots or "").splitlines():
        cle_, _, valeur = ligne.split("#")[0].partition(":")
        cle_, valeur = cle_.strip().lower(), valeur.strip()
        if cle_ == "user-agent":
            agents = [valeur] if nouveau_groupe else agents + [valeur]
            nouveau_groupe = False
        elif cle_ in ("disallow", "allow"):
            nouveau_groupe = True
            if cle_ == "disallow" and valeur == "/":
                bloques.update(r for r in ROBOTS_IA if any(a == "*" or a.lower() == r.lower() for a in agents))
    return sorted(bloques)


def geo(soupe, texte, html_brut, fichiers):
    types, coordonnees = _donnees_structurees(soupe)
    entreprise = [t for t in types if t not in ("WebSite", "WebPage", "BreadcrumbList", "ImageObject", "SearchAction",
                                                "ReadAction", "EntryPoint", "ListItem", "PostalAddress")]
    mots_rendu = len(texte.split())
    mots_brut = len(BeautifulSoup(html_brut or "", "html.parser").get_text(" ").split())
    sans_js = mots_brut >= 30 and mots_brut >= 0.6 * mots_rendu
    bloques = _robots_ia_bloques(fichiers.get("robots"))
    questions = "FAQPage" in types or sum(1 for h in soupe.find_all(["h2", "h3", "h4", "summary"])
                                          if h.get_text(strip=True).endswith("?")) >= 2
    t = texte.lower()
    horaires = bool(re.search(r"horaires|ouvert|lundi|\d{1,2}\s?h\s?\d{0,2}\s?[-–à]\s?\d{1,2}\s?h", t))
    tarifs = bool(re.search(r"tarif|prix|€|devis gratuit", t))
    adresse = bool(re.search(r"\b\d{5}\b", t))
    oui = lambda ok, points: points if ok else 0  # noqa: E731
    return _note([
        ("Données structurées (schema.org)", oui(types, 20), 20,
         ", ".join(sorted(types)[:5]) if types else "aucune : les IA doivent deviner ce que fait l'entreprise"),
        ("Fiche d'entreprise structurée avec coordonnées", oui(entreprise and coordonnees, 15), 15,
         "oui" if entreprise and coordonnees else "pas de fiche LocalBusiness avec adresse ou téléphone"),
        ("Contenu lisible sans JavaScript", oui(sans_js, 20), 20,
         f"{mots_brut} mots dans le code reçu, {mots_rendu} affichés" + ("" if sans_js else " : la plupart des robots d'IA ne verront presque rien")),
        ("Robots d'IA autorisés", oui(not bloques, 15), 15,
         f"bloqués par robots.txt : {', '.join(bloques)}" if bloques else "aucun blocage"),
        ("Contenu en questions-réponses", oui(questions, 10), 10,
         "oui" if questions else "pas de FAQ ni de titres en forme de question"),
        ("Horaires indiqués", oui(horaires, 5), 5, "oui" if horaires else "non trouvés sur l'accueil"),
        ("Tarifs ou devis indiqués", oui(tarifs, 5), 5, "oui" if tarifs else "non trouvés sur l'accueil"),
        ("Adresse avec code postal", oui(adresse, 5), 5, "oui" if adresse else "non trouvée sur l'accueil"),
        ("Fichier llms.txt", oui(fichiers.get("llms"), 5), 5, "présent" if fichiers.get("llms") else "absent"),
    ])


def auditer(html, html_brut, texte, url_finale, ville, mesures, fichiers):
    """Les trois notes mesurées d'un site : {"performance": {...}, "seo": {...}, "geo": {...}}."""
    soupe = BeautifulSoup(html, "html.parser")
    return {"performance": performance(mesures), "seo": seo(soupe, texte, url_finale, ville, fichiers),
            "geo": geo(soupe, texte, html_brut, fichiers), "mesures": mesures or {}}
