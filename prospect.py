"""Outil de prospection : entreprises sans site, avec seulement une page Facebook, ou avec un site cassé / daté.

Exemples :
    python prospect.py --activite auto-ecole --ville Clichy --ville Levallois-Perret --limite 200
    python prospect.py --naf 43.22A --departement 92 --limite 100
    python prospect.py --opposition 123456789 --motif "demande par téléphone le 12/11"

Interface graphique : streamlit run app.py
"""

import argparse
from datetime import date

from prospection import cache, entreprises, oppositions, sites, suivi
from prospection.analyse import analyser
from prospection.config import CONFIG, DOSSIER_DATA, cle
from prospection.export import exporter
from prospection.outils import slug
from prospection.score import calculer


def lire_arguments():
    p = argparse.ArgumentParser(description="Trouve des entreprises sans site ou avec un site daté.")
    p.add_argument("--activite", action="append", default=[], help="nom lisible défini dans activites.yaml (répétable)")
    p.add_argument("--naf", action="append", default=[], help="code NAF, ex. 85.53Z (répétable)")
    p.add_argument("--ville", action="append", default=[], help="nom de commune (répétable)")
    p.add_argument("--cp", action="append", default=[], help="code postal (répétable)")
    p.add_argument("--departement", action="append", default=[], help="code département, ex. 92 (répétable)")
    p.add_argument("--mots-cles", help="recherche libre dans le nom / l'adresse")
    p.add_argument("--limite", type=int, default=50, help="nombre maximum d'entreprises gardées (défaut : 50)")
    p.add_argument("--max-etablissements", type=int, help="exclut les entreprises ayant plus d'établissements")
    p.add_argument("--sans-serpapi", action="store_true", help="ne pas consommer de crédits SerpAPI")
    p.add_argument("--sans-brave", action="store_true", help="ne pas utiliser Brave Search")
    p.add_argument("--sans-pagespeed", action="store_true", help="ne pas appeler PageSpeed Insights")
    p.add_argument("--rafraichir", action="store_true", help="réanalyse les entreprises déjà en cache")
    p.add_argument("--opposition", metavar="SIREN", help="ajoute une entreprise à la liste d'opposition et quitte")
    p.add_argument("--motif", default="", help="motif de l'opposition (avec --opposition)")
    return p.parse_args()


def nom_fichier(args):
    activite = "-".join(args.activite) or "-".join(args.naf) or "tout"
    lieu = "-".join(args.ville) or "-".join(args.cp) or "-".join(args.departement) or "france"
    return DOSSIER_DATA / f"prospects_{slug(activite)[:40]}_{slug(lieu)[:60]}_{date.today().isoformat()}.xlsx"


def analyser_entreprise(fiche, args):
    """Étapes 2 et 3 pour une entreprise, avec cache par SIREN (reprise après interruption)."""
    deja = None if args.rafraichir else cache.lire("analyses", fiche["siren"])
    if deja:
        return deja, True
    site = sites.trouver_site(fiche, avec_serpapi=not args.sans_serpapi, avec_brave=not args.sans_brave)
    # Le nom légal cache parfois une franchise (« ASK AUTO ECOLE » est un CER) : on regarde aussi les titres
    titres = [site["google"].get("titre_google") or "", sites.titre_page(site["accueil"])]
    site["franchise"] = entreprises.mot_franchise(" ".join(titres)) or ""
    analyse = None
    if site["statut"] == "Site actif" and site["accueil"] and site["accueil"]["ok"]:
        analyse = analyser(site["accueil"], site["html_mentions"], avec_pagespeed=not args.sans_pagespeed)
    site = {k: v for k, v in site.items() if k not in ("accueil", "html_mentions")}
    resultat = {"site": site, "analyse": analyse, "date_analyse": date.today().isoformat()}
    cache.ecrire("analyses", fiche["siren"], resultat)
    return resultat, False


def construire_prospect(fiche, resultat, liste_opposition):
    """Assemble fiche + résultat d'analyse + suivi, et calcule le score."""
    opposition = fiche["siren"] in liste_opposition
    if opposition and resultat is None:
        resultat = {"site": {"statut": "Non analysé (opposition)", "url": "", "source": "", "confiance": "",
                             "preuve": "", "google": {}}, "analyse": None, "date_analyse": ""}
    prospect = {"fiche": fiche, **resultat, "opposition": opposition, **suivi.lire(fiche["siren"])}
    prospect["score"] = 0 if opposition else calculer(fiche, resultat["site"], resultat["analyse"])
    return prospect


def afficher_sources():
    serpapi = cle("SERPAPI_KEY")
    print("🔌 Sources : API Recherche d'entreprises ✓, OpenStreetMap ✓, devinette de domaine ✓"
          f", Google Maps (SerpAPI) {'✓' if serpapi else '✗ pas de clé'}"
          f", Brave {'✓' if cle('BRAVE_API_KEY') else '✗ pas de clé'}"
          f", PageSpeed {'✓' if cle('PAGESPEED_API_KEY') else '✗ pas de clé'}")
    if serpapi:
        print(f"   SerpAPI ce mois-ci : {cache.compteur('serpapi')} / {CONFIG['serpapi']['plafond_mensuel']} appels")


def executer(args, progression=None):
    """Lance une recherche complète et renvoie (prospects, chemin de l'Excel).

    `progression(i, total, prospect)` est appelée après chaque entreprise (utilisée par l'interface).
    """
    if args.max_etablissements is not None:
        CONFIG["exclusions"]["max_etablissements"] = args.max_etablissements

    print("\n① Recherche des entreprises")
    naf = entreprises.codes_naf(args.activite, args.naf)
    communes = entreprises.codes_communes(args.ville)
    fiches, nb_exclues = entreprises.rechercher(naf, communes, args.cp, args.departement, args.mots_cles, args.limite)
    print(f"  ✅ {len(fiches)} entreprises gardées, {nb_exclues} exclues")

    liste_opposition = oppositions.lire()
    a_analyser = [f for f in fiches if f["siren"] not in liste_opposition]
    if len(a_analyser) < len(fiches):
        print(f"  🚫 {len(fiches) - len(a_analyser)} entreprise(s) en opposition : non analysées")

    print("\n② Recherche et analyse des sites")
    nouvelles = [f for f in a_analyser if args.rafraichir or cache.lire("analyses", f["siren"]) is None]
    sites.prechercher_openstreetmap(nouvelles)

    prospects = []
    try:
        for i, fiche in enumerate(fiches, start=1):
            resultat, en_cache = (None, False) if fiche["siren"] in liste_opposition \
                else analyser_entreprise(fiche, args)
            prospect = construire_prospect(fiche, resultat, liste_opposition)
            prospects.append(prospect)
            site = prospect["site"]
            print(f"  [{i}/{len(fiches)}] {(fiche['enseigne'] or fiche['nom'])[:38]:38} "
                  f"{prospect['score']:3}  {site['statut']}{' — ' + site['url'] if site['url'] else ''}"
                  f"{'  (cache)' if en_cache else ''}")
            if progression:
                progression(i, len(fiches), prospect)
    except KeyboardInterrupt:
        print("\n⏸️  Interrompu : export des résultats déjà obtenus. Relance la même commande pour reprendre.")

    if not prospects:
        print("Aucune entreprise à exporter.")
        return prospects, None
    criteres = " ".join(f'--{k.replace("_", "-")} "{x}"' for k, v in vars(args).items()
                        if v and k in ("activite", "naf", "ville", "cp", "departement", "mots_cles", "limite")
                        for x in (v if isinstance(v, list) else [v]))
    chemin = exporter(prospects, nom_fichier(args), criteres)
    print(f"\n④ 📊 Fichier Excel : {chemin}")
    return prospects, chemin


def main():
    args = lire_arguments()
    if args.opposition:
        oppositions.ajouter(args.opposition, args.motif)
        return
    afficher_sources()
    executer(args)


if __name__ == "__main__":
    main()
