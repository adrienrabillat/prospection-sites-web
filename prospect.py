"""Trouve, dans une ville, les entreprises indépendantes dont le site est fait maison, amateur ou très daté.

    .venv/bin/python prospect.py "Clichy"
    .venv/bin/python prospect.py "Levallois-Perret" --budget 8
    .venv/bin/python prospect.py "Clichy" --limite 20        # essai rapide sur 20 sites

Tout est mémorisé dans prospection.sqlite : relancer la même commande reprend où l'on s'était arrêté,
sans revisiter ni repayer ce qui est déjà fait. Interface graphique : streamlit run app.py
"""

import argparse
import sys

from prospection import base, collecte, jugement, potentiel, rapport, visite
from prospection.config import CONFIG, verifier_cle_anthropic


def lire_arguments():
    p = argparse.ArgumentParser(description="Entreprises d'une ville dont le site est à refaire.")
    p.add_argument("ville", help="nom de la ville (ou code postal)")
    p.add_argument("--budget", type=float, default=CONFIG["budget"]["par_ville_usd"],
                   help=f"dépense Anthropic maximale pour ce lancement, en dollars (défaut : {CONFIG['budget']['par_ville_usd']})")
    p.add_argument("--limite", type=int, help="ne traiter que les N premiers sites (pour un essai)")
    p.add_argument("--sans-google", action="store_true", help="ne pas utiliser le quota Google Maps (SerpAPI)")
    p.add_argument("--visites-seulement", action="store_true",
                   help="trouver et visiter les sites sans les faire juger (gratuit, sans clé Anthropic)")
    p.add_argument("--refaire", action="store_true", help="revisiter et rejuger les sites déjà traités")
    return p.parse_args()


def executer(ville, budget, limite=None, sans_google=False, refaire=False, visites_seulement=False, journal=print):
    """Lance toute la chaîne pour une ville. Renvoie (groupes de prospects, chemin Excel, chemin de la page)."""
    probleme = None if visites_seulement else verifier_cle_anthropic(jugement.MODELE)
    if probleme:
        raise SystemExit(f"Clé Anthropic : {probleme}.\nPour avancer sans elle : ajoute --visites-seulement "
                         "(trouve et visite les sites, gratuit), puis relance quand la clé est prête.")
    if visites_seulement:
        budget = 0.0
    reste_total = CONFIG["budget"]["total_usd"] - base.depense_totale()
    budget = min(budget, max(0.0, reste_total))
    journal(f"💶 Budget de ce lancement : {budget:.2f} $ (déjà dépensé en tout : {base.depense_totale():.2f} $ "
            f"sur {CONFIG['budget']['total_usd']} $)")

    com = collecte.commune(ville)
    nom = com["nom"]
    habitants = f"{com['population']:,}".replace(",", " ")
    journal(f"\n① Entreprises de {nom} ({com['departement']}, {habitants} habitants) qui ont un site")
    candidats, sans_site, depense = collecte.collecter(com, budget_ia=budget * 0.25, avec_google=not sans_google, journal=journal)
    candidats.sort(key=lambda c: c["cle"])
    if limite:
        candidats = candidats[:limite]
    journal(f"  ✅ {len(candidats)} sites d'entreprises à examiner")

    # À voir : jamais visités, ou visités avant l'ajout de l'audit (performance, SEO, GEO)
    a_visiter = [c for c in candidats if refaire or not c.get("visite")
                 or (c["visite"]["etat"] == "ok" and "audit" not in c["visite"])]
    journal(f"\n② Visite des sites ({len(a_visiter)} à voir, {len(candidats) - len(a_visiter)} déjà vus)")
    compte = {"n": 0}

    def apres_visite(c):
        compte["n"] += 1
        base.enregistrer(c)
        v = c["visite"]
        etat = "✓" if v["etat"] == "ok" else f"✗ {v['etat']} : {v['motif']}"
        journal(f"  [{compte['n']}/{len(a_visiter)}] {c['nom'][:34]:34} {c['domaine'][:36]:36} {etat}")

    try:
        visite.visiter(a_visiter, nom, apres_visite)
    except KeyboardInterrupt:
        journal("\n⏸️  Visites interrompues : relance la même commande pour reprendre.")

    a_juger = [] if visites_seulement else [c for c in candidats if (c.get("visite") or {}).get("etat") == "ok"
               and c["visite"].get("capture_ordinateur") and "audit" in c["visite"]
               and (refaire or not jugement.a_jour(c))]
    reste = budget - depense
    if visites_seulement:
        journal("\n③ Jugement par Claude : pas cette fois (--visites-seulement). Relance sans cette option pour juger.")
    else:
        journal(f"\n③ Jugement par Claude ({jugement.MODELE}) : {len(a_juger)} sites, "
                f"≈ {len(a_juger) * jugement.cout_moyen():.2f} $ (budget restant : {reste:.2f} $)")
    compte["n"] = 0

    def apres_jugement(c, erreur):
        compte["n"] += 1
        if erreur:
            journal(f"  [{compte['n']}/{len(a_juger)}] {c['nom'][:34]:34} ⚠️  {erreur}")
            return
        base.enregistrer(c)
        v = c["verdict"]
        a = c["visite"]["audit"]
        notes = " ".join(f"{nom} {'--' if n is None else n:>3}" for nom, n in (
            ("design", v["note_design"]), ("perf", a["performance"]["note"]), ("seo", a["seo"]["note"]),
            ("geo", a["geo"]["note"])))
        journal(f"  [{compte['n']}/{len(a_juger)}] {c['nom'][:30]:30} {v['score']:3}  [{notes}]  {v['niveau_site']}"
                + ("" if v["proprietaire"] == rapport.INDEPENDANTE else f" — écarté : {v['proprietaire']}"))

    try:
        juges, cout, non_juges = jugement.juger_lot(a_juger, nom, reste, apres_jugement)
        depense += cout
        if non_juges:
            journal(f"  ⚠️  Budget atteint : {non_juges} site(s) non jugé(s). Relance avec un budget pour les finir.")
    except KeyboardInterrupt:
        journal("\n⏸️  Jugements interrompus : les verdicts obtenus sont gardés.")

    if not visites_seulement:
        # Potentiel : tout sauf les sites que le verdict a déjà écartés (chaînes, plateformes…)
        a_noter = [c for c in candidats + sans_site if "potentiel" not in c
                   and (c.get("verdict") or {}).get("proprietaire", rapport.INDEPENDANTE) == rapport.INDEPENDANTE]
        journal(f"\n④ Potentiel commercial (métier, avis Google, registre des entreprises) : {len(a_noter)} entreprises")
        depense += potentiel.qualifier(a_noter, com, CONFIG["budget"]["total_usd"] - base.depense_totale(), journal)

    connus = {x["cle"] for x in candidats + sans_site}
    groupes, chemin_excel, chemin_page = rapport.produire([c for c in base.candidats(nom) if c["cle"] in connus], nom)
    p = groupes["prospects"]
    journal(f"\n⑤ Résultat pour {nom} (entreprises à bon potentiel seulement)")
    journal(f"  🎯 Site à refaire : {sum(1 for c in p if c['verdict']['score'] >= 80)} excellents prospects (80+), "
            f"{sum(1 for c in p if 60 <= c['verdict']['score'] < 80)} bons (60 à 79), sur {len(p)} retenus")
    journal(f"  🚫 Sans site : {len(groupes['sans_site'])} retenues · 📉 potentiel faible : {len(groupes['faible'])}")
    journal(f"  🔧 {len(groupes['casses'])} sites cassés · {len(groupes['ecartes'])} écartés (chaînes, "
            f"plateformes…) · {len(groupes['a_voir'])} à voir à la main")
    for c in p[:10]:
        journal(f"     {c['verdict']['score']:3}  {c['nom'][:34]:34} {c['domaine']}")
    journal(f"  💶 Dépense de ce lancement : {depense:.2f} $ (total : {base.depense_totale():.2f} $)")
    journal(f"  📊 Excel : {chemin_excel}")
    journal(f"  🌐 Page avec les captures : {chemin_page}")
    return groupes, chemin_excel, chemin_page


def main():
    args = lire_arguments()
    sys.stdout.reconfigure(line_buffering=True)
    executer(args.ville, args.budget, args.limite, args.sans_google, args.refaire, args.visites_seulement)


if __name__ == "__main__":
    main()
