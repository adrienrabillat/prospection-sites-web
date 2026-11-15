"""Interface de l'outil de prospection : streamlit run app.py (ou double-clic sur lancer.command)."""

import subprocess
import sys

import pandas as pd
import streamlit as st

from prospection import base, rapport
from prospection.config import CONFIG, DOSSIER_DATA, RACINE, cle, enregistrer_cle
from prospection.outils import slug

st.set_page_config(page_title="Prospection de sites à refaire", page_icon="🎯", layout="wide")
st.title("🎯 Sites à refaire")
onglet_prospects, onglet_ville, onglet_reglages = st.tabs(["📋 Prospects", "🔎 Nouvelle ville", "⚙️ Réglages"])


# --- Prospects --------------------------------------------------------------------------------

with onglet_prospects:
    villes = base.villes()
    if not villes:
        st.info("Aucune ville analysée pour l'instant : lance une recherche dans l'onglet « Nouvelle ville ».")
    else:
        c1, c2, c3, c4 = st.columns([2, 2, 3, 3])
        ville = c1.selectbox("Ville", ["Toutes"] + villes)
        score_min = c2.slider("Score minimum", 0, 100, 60, step=5)
        niveaux = c3.multiselect("Niveau du site", ["fait maison ou amateur", "daté", "correct mais perfectible",
                                                    "professionnel et récent", "vide, en construction ou cassé"])
        texte = c4.text_input("Recherche", placeholder="nom, activité, problème…")

        groupes = rapport.trier(base.candidats(None if ville == "Toutes" else ville))
        prospects = {c["cle"]: c for c in groupes["prospects"]}
        lignes = [rapport.ligne(c) for c in prospects.values()]
        lignes = [x for x in lignes if x["Score"] >= score_min
                  and (not niveaux or x["Niveau du site"] in niveaux)
                  and texte.lower() in " ".join(str(v) for v in x.values()).lower()]
        st.caption(f"{len(lignes)} prospects affichés sur {len(prospects)} sites jugés · "
                   f"{len(groupes['casses'])} sites cassés · {len(groupes['ecartes'])} écartés · "
                   f"{len(groupes['a_voir'])} à voir à la main · {len(groupes['sans_site'])} sans site · "
                   f"{len(groupes['faible'])} à potentiel faible (masqués)")

        if lignes:
            tableau = pd.DataFrame(lignes).set_index("cle")
            colonnes = ["Score", "Entreprise", "Activité", "Intérêt d'un site", "Santé", "Design", "Performance", "SEO", "GEO",
                        "Niveau du site",
                        "Fait maison", "Suivi", "Notes",
                        "Téléphone", "E-mail", "Site", "Note Google", "Avis", "Accroche", "Ville"]
            modifie = st.data_editor(
                tableau[colonnes], hide_index=True, width="stretch", height=420,
                disabled=[c for c in colonnes if c not in ("Suivi", "Notes")],
                column_config={"Suivi": st.column_config.SelectboxColumn(options=base.ETATS, required=True),
                               "Site": st.column_config.LinkColumn(),
                               "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})
            changes = modifie[(modifie["Suivi"] != tableau["Suivi"]) | (modifie["Notes"] != tableau["Notes"])]
            if len(changes) and st.button(f"💾 Enregistrer le suivi ({len(changes)} modification(s))", type="primary"):
                for cle_site, x in changes.iterrows():
                    base.noter_suivi(cle_site, x["Suivi"], x["Notes"])
                st.rerun()

            choix = st.selectbox("Voir un prospect en détail", [x["cle"] for x in lignes],
                                 format_func=lambda k: f"{prospects[k]['verdict']['score']} — {prospects[k]['nom']}")
            c, v = prospects[choix], prospects[choix]["verdict"]
            gauche, droite = st.columns([3, 2])
            dossier = DOSSIER_DATA / slug(c["ville"])
            images = [dossier / c["visite"][k] for k in ("capture_ordinateur", "capture_mobile") if c["visite"].get(k)]
            with gauche:
                grande, petite = st.columns([3, 1])
                for zone, image in zip((grande, petite), images):
                    if image.exists():
                        zone.image(str(image))
            with droite:
                st.subheader(c["nom"])
                st.markdown(f"**{v['score']} / 100** · {v['niveau_site']} · fait maison : {v['fait_maison']} · "
                            f"mobile : {v['version_mobile']}")
                st.markdown(f"[{c['domaine']}]({c['visite']['url_finale']})")
                for zone, (nom, note) in zip(st.columns(4), rapport.notes(c).items()):
                    zone.metric(nom, "–" if note is None else f"{note}/100")
                st.write(v["resume"])
                st.markdown("\n".join(f"- {p}" for p in v["problemes"]))
                st.info(v["accroche"])
                with st.expander("Détail du référentiel"):
                    for nom, liste in rapport.defauts_mesures(c).items():
                        if liste:
                            st.markdown(f"**{nom}**, critères ratés :\n" + "\n".join(f"- {d}" for d in liste))
                coord = rapport.contact(c)
                st.caption(" · ".join(x for x in (coord["telephone"], coord["email"], c.get("adresse")) if x))

        with st.expander(f"Entreprises sans site ({len(groupes['sans_site'])})"):
            st.dataframe(pd.DataFrame([rapport.ligne_sans_site(c) for c in groupes["sans_site"]]).drop(columns="cle", errors="ignore"),
                         hide_index=True, width="stretch")

        with st.expander(f"Sites cassés ou disparus ({len(groupes['casses'])})"):
            st.dataframe(pd.DataFrame([{"Entreprise": c["nom"], "Site": c["url"], "Motif": c["visite"]["motif"],
                                        "Téléphone": rapport.contact(c)["telephone"]} for c in groupes["casses"]]),
                         hide_index=True, width="stretch")


# --- Nouvelle ville ---------------------------------------------------------------------------

with onglet_ville:
    reste = CONFIG["budget"]["total_usd"] - base.depense_totale()
    st.write("Donne une ville : l'outil trouve les entreprises qui ont un site (OpenStreetMap et Google Maps), "
             "visite chaque site, mesure sa vitesse, son SEO et son GEO, puis Claude juge les captures d'écran. Compte 30 à 45 minutes par ville.")
    with st.form("ville"):
        c1, c2 = st.columns([3, 1])
        nouvelle = c1.text_input("Ville", placeholder="Clichy")
        budget = c2.number_input("Budget (dollars)", 1.0, max(1.0, float(reste)),
                                 min(float(CONFIG["budget"]["par_ville_usd"]), max(1.0, float(reste))), step=1.0)
        lancer = st.form_submit_button("Lancer", type="primary", disabled=not cle("ANTHROPIC_API_KEY"))
    if not cle("ANTHROPIC_API_KEY"):
        st.warning("Renseigne d'abord ta clé Anthropic dans l'onglet « Réglages ».")
    if lancer and nouvelle.strip():
        zone, lignes_journal = st.empty(), []
        processus = subprocess.Popen([sys.executable, "-u", str(RACINE / "prospect.py"), nouvelle.strip(),
                                      "--budget", str(budget)], cwd=RACINE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        for sortie in processus.stdout:
            lignes_journal.append(sortie.rstrip())
            zone.code("\n".join(lignes_journal[-25:]))
        if processus.wait() == 0:
            st.success("Terminé : les résultats sont dans l'onglet « Prospects » (recharge la page).")
        else:
            st.error("Le script s'est arrêté sur une erreur (voir les dernières lignes ci-dessus).")


# --- Réglages ---------------------------------------------------------------------------------

with onglet_reglages:
    st.metric("Dépense Anthropic totale", f"{base.depense_totale():.2f} $", f"plafond : {CONFIG['budget']['total_usd']} $",
              delta_color="off")
    st.caption(f"Google Maps (SerpAPI) : {base.compteur('serpapi')} recherches ce mois-ci sur "
               f"{CONFIG['google_maps']['plafond_mensuel']}. Une ville en consomme {len(CONFIG['metiers'])}.")
    for nom, libelle in (("ANTHROPIC_API_KEY", "Clé Anthropic (jugement des sites, payant à l'usage)"),
                         ("SERPAPI_KEY", "Clé SerpAPI (Google Maps, 250 recherches gratuites par mois)")):
        with st.form(nom, clear_on_submit=True):
            st.write(f"**{libelle}** : {'✅ enregistrée' if cle(nom) else '❌ absente'}")
            valeur = st.text_input("Nouvelle clé", type="password", label_visibility="collapsed")
            if st.form_submit_button("Enregistrer") and valeur.strip():
                enregistrer_cle(nom, valeur)
                st.rerun()
    st.caption("Métiers cherchés, plafonds, modèle : fichier `config.yaml`.")
