"""Étape 1 — Récupérer les entreprises via l'API Recherche d'entreprises (gratuite, sans clé).

Documentation : https://recherche-entreprises.api.gouv.fr/docs/
- 7 requêtes / s maximum par IP, 25 résultats par page, 10 000 résultats maximum par recherche.
- `activite_principale` filtre l'unité légale ; les filtres géographiques filtrent les établissements.
"""

import json
from pathlib import Path

from . import cache
from .config import ACTIVITES, CONFIG
from .outils import contient_mot, normaliser
from .reseau import appel_api

URL_API = "https://recherche-entreprises.api.gouv.fr/search"
URL_GEO = "https://geo.api.gouv.fr/communes"
PAR_PAGE = 25

_libelles = Path(__file__).parent / "libelles"
LIBELLES_NAF = json.loads((_libelles / "codes-NAF.json").read_text(encoding="utf-8"))
TRANCHES = json.loads((_libelles / "tranches-effectifs.json").read_text(encoding="utf-8"))
TRANCHES.update({"NN": "Non employeur", "00": "0 salarié"})

# Communes découpées en arrondissements : l'API attend les codes des arrondissements
COMMUNES_ARRONDISSEMENTS = {"75056": "Paris", "69123": "Lyon", "13055": "Marseille"}


def codes_naf(activites, codes):
    """Traduit les noms d'activité (activites.yaml) en codes NAF, et ajoute les codes donnés tels quels."""
    index = {normaliser(nom): valeurs for nom, valeurs in ACTIVITES.items()}
    resultat = list(codes or [])
    for activite in activites or []:
        trouve = index.get(normaliser(activite))
        if not trouve:
            connues = ", ".join(sorted(ACTIVITES))
            raise SystemExit(f"Activité inconnue : « {activite} ». Ajoute-la dans activites.yaml.\n"
                             f"Activités connues : {connues}")
        resultat += trouve
    return sorted(set(resultat))


def codes_communes(villes):
    """Nom de ville -> code(s) commune INSEE, via geo.api.gouv.fr (gratuit, sans clé)."""
    codes = []
    for ville in villes or []:
        communes = appel_api(URL_GEO, {"nom": ville, "fields": "nom,code,codeDepartement",
                                       "boost": "population", "limit": 5})
        exactes = [c for c in communes if normaliser(c["nom"]) == normaliser(ville)]
        if not (exactes or communes):
            raise SystemExit(f"Ville introuvable : « {ville} »")
        commune = (exactes or communes)[0]
        if commune["code"] in COMMUNES_ARRONDISSEMENTS:
            arrondissements = appel_api(URL_GEO, {"nom": commune["nom"], "type": "arrondissement-municipal",
                                                  "fields": "code", "limit": 30})
            codes += [a["code"] for a in arrondissements]
        else:
            codes.append(commune["code"])
        print(f"  📍 {ville} → {commune['nom']} ({commune['code']}, {commune['codeDepartement']})")
    return codes


def _dirigeants(resultat):
    noms = []
    for d in resultat.get("dirigeants") or []:
        if "commissaire" in (d.get("qualite") or "").lower():
            continue
        if d.get("type_dirigeant") == "personne morale":
            nom = d.get("denomination") or ""
        else:
            nom = f"{(d.get('prenoms') or '').split(' ')[0].title()} {d.get('nom') or ''}".strip()
        if nom:
            noms.append(f"{nom} ({d['qualite']})" if d.get("qualite") else nom)
    return ", ".join(noms[:3])


def _etablissement_local(resultat):
    """Établissement actif qui correspond aux filtres géographiques (sinon le siège)."""
    actifs = [e for e in resultat.get("matching_etablissements") or [] if e.get("etat_administratif") == "A"]
    actifs.sort(key=lambda e: not e.get("est_siege"))
    return actifs[0] if actifs else None


def _nombre(valeur):
    """Coordonnée en nombre, ou None (l'API renvoie « [NON-DIFFUSIBLE] » pour les données masquées)."""
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def extraire(resultat):
    """Transforme un résultat brut de l'API en fiche entreprise à plat."""
    siege = resultat.get("siege") or {}
    etab = _etablissement_local(resultat) or siege
    enseignes = etab.get("liste_enseignes") or siege.get("liste_enseignes") or []
    enseigne = etab.get("nom_commercial") or (enseignes[0] if enseignes else "")
    naf = resultat.get("activite_principale") or ""
    finances = resultat.get("finances") or {}
    derniere_annee = max(finances) if finances else None
    return {
        "siren": resultat["siren"],
        "siret_siege": siege.get("siret"),
        "siret_local": etab.get("siret"),
        "nom": resultat.get("nom_raison_sociale") or resultat.get("nom_complet") or "",
        "nom_complet": resultat.get("nom_complet") or "",
        "enseigne": enseigne.title() if enseigne.isupper() else enseigne,
        "adresse": etab.get("adresse") or "",
        "code_postal": etab.get("code_postal") or "",
        "ville": (etab.get("libelle_commune") or "").title(),
        "latitude": _nombre(etab.get("latitude")),
        "longitude": _nombre(etab.get("longitude")),
        # « P » = diffusion partielle : l'entrepreneur s'est opposé à l'usage de ses données par des tiers
        "diffusible": resultat.get("statut_diffusion", "O") == "O"
        and etab.get("statut_diffusion_etablissement", "O") == "O" and "NON-DIFFUSIBLE" not in str(etab),
        "naf": naf,
        "libelle_naf": LIBELLES_NAF.get(naf, ""),
        "date_creation": resultat.get("date_creation") or "",
        "tranche_effectif": TRANCHES.get(resultat.get("tranche_effectif_salarie") or "", ""),
        "nb_etablissements": resultat.get("nombre_etablissements_ouverts") or 0,
        "dirigeants": _dirigeants(resultat),
        "entrepreneur_individuel": (resultat.get("complements") or {}).get("est_entrepreneur_individuel"),
        "chiffre_affaires": (finances.get(derniere_annee) or {}).get("ca") if derniere_annee else None,
        "a_un_etablissement_local": _etablissement_local(resultat) is not None,
    }


def motif_exclusion(fiche):
    """Renvoie la raison de l'exclusion, ou None si l'entreprise est gardée."""
    if not fiche["a_un_etablissement_local"]:
        return "aucun établissement actif dans la zone"
    if not fiche["diffusible"]:
        return "non diffusible (opposé à l'usage de ses données, à ne pas prospecter)"
    regles = CONFIG["exclusions"]
    if fiche["nb_etablissements"] > regles["max_etablissements"]:
        return f"{fiche['nb_etablissements']} établissements (réseau)"
    mot = mot_franchise(f"{fiche['nom_complet']} {fiche['enseigne']}")
    if mot:
        return f"franchise / réseau ({mot})"
    return None


def mot_franchise(texte):
    """Premier mot de la liste `franchises` présent (en mot entier) dans le texte, sinon None."""
    for mot in CONFIG["exclusions"]["franchises"]:
        if contient_mot(texte, mot):
            return mot
    return None


def rechercher(naf=None, communes=None, codes_postaux=None, departements=None, mots_cles=None, limite=50):
    """Interroge l'API page par page et renvoie (fiches gardées, nb exclues)."""
    params = {"etat_administratif": "A", "per_page": PAR_PAGE, "limite_matching_etablissements": 20}
    if naf:
        params["activite_principale"] = ",".join(naf)
    if communes:
        params["code_commune"] = ",".join(communes)
    if codes_postaux:
        params["code_postal"] = ",".join(codes_postaux)
    if departements:
        params["departement"] = ",".join(departements)
    if mots_cles:
        params["q"] = mots_cles
    if len(params) == 3:
        raise SystemExit("Donne au moins un filtre : activité, NAF, ville, code postal, département ou mots-clés.")

    gardees, exclues, page = [], 0, 1
    while len(gardees) < limite and page * PAR_PAGE <= 10_000:
        reponse = appel_api(URL_API, {**params, "page": page})
        if page == 1:
            print(f"  🏢 {reponse.get('total_results', 0)} entreprises actives trouvées par l'API")
        for brut in reponse.get("results", []):
            fiche = extraire(brut)
            cache.ecrire("entreprises", fiche["siren"], fiche)
            motif = motif_exclusion(fiche)
            if motif:
                exclues += 1
                print(f"    ✗ {fiche['nom_complet'][:45]:45} exclue : {motif}")
                continue
            gardees.append(fiche)
            if len(gardees) >= limite:
                break
        if page >= reponse.get("total_pages", 0):
            break
        page += 1
    return gardees, exclues
