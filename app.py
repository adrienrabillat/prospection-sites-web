"""Interface locale de l'outil de prospection.

Lancement : .venv/bin/streamlit run app.py   (s'ouvre sur http://localhost:8501)
Thème : .streamlit/config.toml — icônes : Material Symbols intégrés à Streamlit (syntaxe :material/nom:).
"""

import argparse
from datetime import date

import pandas as pd
import streamlit as st

import prospect
from prospection import cache, oppositions, suivi
from prospection.config import ACTIVITES, CONFIG, DOSSIER_DATA, cle, enregistrer_cle
from prospection.export import LIBELLES_SIGNAUX, exporter
from prospection.reseau import ErreurAPI, appel_api

st.set_page_config(page_title="Prospection", page_icon=":material/travel_explore:", layout="wide")

URL_ANNUAIRE = "https://annuaire-entreprises.data.gouv.fr/entreprise/"

# Ajustements que le thème ne couvre pas : marges de page, respiration des formulaires, étiquettes discrètes.
# Uniquement des sélecteurs data-testid / baseweb, stables d'une version de Streamlit à l'autre.
STYLE = """
<style>
.block-container { padding: 2.5rem 3rem 4rem; max-width: 1440px; }
[data-testid="stHeader"] { background: transparent; }
h1 { letter-spacing: -0.02em; }
[data-testid="stForm"] { padding: 1.75rem 2rem; }
[data-testid="stForm"] [data-testid="stVerticalBlock"] { gap: 1.4rem; }
.st-key-reglages [data-testid="stForm"] { padding: 0.5rem 0; }
[data-testid="stWidgetLabel"] p { font-size: 0.82rem; font-weight: 500; color: #9AA3B2; letter-spacing: 0.01em; }
.stTabs [data-baseweb="tab-list"] { gap: 2rem; border-bottom: 1px solid #2C313A; margin-bottom: 1.5rem; }
.stTabs [data-baseweb="tab"] { padding: 0.9rem 0.1rem; }
.stTabs [data-baseweb="tab-highlight"] { height: 2px; }
[data-testid="stMetric"] { padding: 0.25rem 0.5rem; }
[data-testid="stMetricLabel"] p { color: #9AA3B2; }
</style>
"""


# --- Outils -----------------------------------------------------------------------------------

def masquer(valeur):
    return f"{valeur[:4]}…{valeur[-4:]}" if valeur and len(valeur) > 10 else "••••"


def compte_serpapi(cle_api):
    """Interroge l'API Compte de SerpAPI (gratuite, ne consomme pas de recherche)."""
    try:
        return appel_api("https://serpapi.com/account.json", {"api_key": cle_api}, tentatives=1), None
    except ErreurAPI as erreur:
        if "HTTP 401" in str(erreur):
            return None, "clé invalide"
        return None, str(erreur).replace(cle_api, "***")


def charger_prospects():
    """Toutes les entreprises déjà analysées (toutes recherches confondues)."""
    fiches = cache.tout("entreprises")
    liste_opposition = oppositions.lire()
    prospects = []
    for siren, resultat in cache.tout("analyses").items():
        if siren in fiches and fiches[siren].get("diffusible", True):
            prospects.append(prospect.construire_prospect(fiches[siren], resultat, liste_opposition))
    return prospects


def en_tableau(prospects):
    lignes = []
    for p in prospects:
        f, s, a = p["fiche"], p["site"], p.get("analyse") or {}
        lignes.append({
            "SIREN_cle": f["siren"],
            "Score": p["score"],
            "Nom": f["enseigne"] or f["nom"],
            "Ville": f["ville"],
            "Activité": f["libelle_naf"],
            "Statut web": s["statut"],
            "URL": s["url"],
            "Téléphone": s.get("telephone") or (s.get("google") or {}).get("telephone") or "",
            "E-mail": a.get("email", ""),
            "Dirigeant": f["dirigeants"],
            "Confiance": s["confiance"],
            "Franchise": (s.get("franchise") or "").upper(),
            "CMS": a.get("cms", ""),
            "Signaux": ", ".join(LIBELLES_SIGNAUX.get(x, x) for x in a.get("signaux", [])),
            "Création": f["date_creation"][:4],
            "SIREN": URL_ANNUAIRE + f["siren"],
            "SIRET": f.get("siret_local") or f.get("siret_siege") or "",
            "Suivi": suivi.OPPOSITION if p["opposition"] else p.get("suivi", ""),
            "Notes": p.get("notes", ""),
        })
    colonnes = ["SIREN_cle", "Score", "Nom", "Ville", "Statut web", "Téléphone", "Suivi", "Notes", "URL", "E-mail",
                "Dirigeant", "Activité", "Confiance", "Franchise", "CMS", "Signaux", "Création", "SIREN", "SIRET"]
    return pd.DataFrame(lignes, columns=colonnes).sort_values("Score", ascending=False).set_index("SIREN_cle")


CONFIG_COLONNES = {
    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d", width="small"),
    "URL": st.column_config.LinkColumn("URL", display_text=r"https?://(?:www\.)?([^/]+)"),
    "SIREN": st.column_config.LinkColumn("SIREN", display_text=r".*/entreprise/(\d+)", width="small"),
    "Suivi": st.column_config.SelectboxColumn("Suivi", options=suivi.ETATS, width="medium"),
    "Notes": st.column_config.TextColumn("Notes", width="large"),
}


# --- Onglet : réglages ------------------------------------------------------------------------

def onglet_reglages():
    with st.container(border=True, key="reglages"):
        st.subheader(":material/key: Clé SerpAPI (Google Maps)")
        st.caption("Plan gratuit : 250 recherches par mois, une par entreprise analysée. "
                   "Crée ta clé sur [serpapi.com/manage-api-key](https://serpapi.com/manage-api-key). "
                   "Elle est enregistrée uniquement dans le fichier `.env` de ce dossier, sur ton ordinateur.")

        actuelle = cle("SERPAPI_KEY")
        if actuelle:
            st.success(f"Clé enregistrée : `{masquer(actuelle)}`", icon=":material/check_circle:")

        with st.form("cle_serpapi", clear_on_submit=True, border=False):
            nouvelle = st.text_input("Nouvelle clé SerpAPI", type="password", placeholder="Colle ta clé ici")
            envoyer = st.form_submit_button("Enregistrer et tester", type="primary", icon=":material/verified:")
            if envoyer and nouvelle.strip():
                compte, erreur = compte_serpapi(nouvelle.strip())
                if erreur:
                    st.error(f"Clé refusée par SerpAPI : {erreur}", icon=":material/error:")
                else:
                    enregistrer_cle("SERPAPI_KEY", nouvelle)
                    st.rerun()

        if actuelle:
            compte, erreur = compte_serpapi(actuelle)
            if compte:
                c1, c2, c3 = st.columns(3, gap="large")
                c1.metric("Plan", compte.get("plan_name", "?"), border=True)
                c2.metric("Recherches restantes", f"{compte.get('total_searches_left', '?')}", border=True,
                          help="Selon SerpAPI, tous crédits confondus")
                c3.metric("Utilisées ce mois-ci", f"{compte.get('this_month_usage', '?')} / "
                                                  f"{compte.get('searches_per_month', '?')}", border=True)
            elif erreur:
                st.warning(f"Impossible de vérifier le compte : {erreur}", icon=":material/warning:")
            st.caption(f"Plafond de sécurité de l'outil : {CONFIG['serpapi']['plafond_mensuel']} appels par mois "
                       f"({cache.compteur('serpapi')} déjà faits ce mois-ci). Modifiable dans `config.yaml`.")
            if st.button("Supprimer la clé", icon=":material/delete:"):
                enregistrer_cle("SERPAPI_KEY", "")
                st.rerun()

    with st.expander("Autres clés (optionnelles)", icon=":material/tune:"):
        autres = {"PAGESPEED_API_KEY": "Google PageSpeed Insights (gratuit avec une clé Google Cloud)",
                  "BRAVE_API_KEY": "Brave Search (5 $ de crédit offert par mois, carte bancaire requise)",
                  "CONTACT_EMAIL": "Ton e-mail, ajouté au User-Agent envoyé aux APIs"}
        for nom, description in autres.items():
            valeur = cle(nom)
            saisie = st.text_input(f"{description}", key=nom, type="password" if "KEY" in nom else "default",
                                   placeholder=f"Actuelle : {masquer(valeur)}" if valeur else "")
            if saisie and st.button(f"Enregistrer {nom}", key=f"btn_{nom}", icon=":material/save:"):
                enregistrer_cle(nom, saisie)
                st.success(f"{nom} enregistrée", icon=":material/check_circle:")


# --- Onglet : nouvelle recherche --------------------------------------------------------------

def onglet_recherche():
    serpapi = cle("SERPAPI_KEY")
    if not serpapi:
        st.info("Pas de clé SerpAPI : la recherche utilisera seulement OpenStreetMap et la devinette de domaine. "
                "Ajoute ta clé dans l'onglet **Réglages** pour des résultats plus fiables.", icon=":material/info:")

    with st.form("recherche"):
        c1, c2 = st.columns(2, gap="large")
        activites = c1.multiselect("Activité(s)", sorted(ACTIVITES), placeholder="ex. auto-ecole")
        naf = c2.text_input("Ou code(s) NAF", placeholder="ex. 85.53Z, 43.22A")
        c1, c2, c3 = st.columns([2, 1, 1], gap="large")
        villes = c1.text_input("Ville(s)", placeholder="ex. Clichy, Levallois-Perret")
        departements = c2.text_input("Ou département(s)", placeholder="ex. 92")
        limite = c3.number_input("Nombre max d'entreprises", min_value=1, max_value=2000, value=20, step=10)
        c1, c2, c3 = st.columns(3, gap="large")
        avec_serpapi = c1.toggle("Google Maps (SerpAPI)", value=bool(serpapi), disabled=not serpapi)
        avec_pagespeed = c2.toggle("Score PageSpeed", value=False, disabled=not cle("PAGESPEED_API_KEY"))
        rafraichir = c3.toggle("Réanalyser les entreprises déjà vues", value=False)
        lancer = st.form_submit_button("Lancer la recherche", type="primary", icon=":material/search:")

    if serpapi and avec_serpapi:
        reste = CONFIG["serpapi"]["plafond_mensuel"] - cache.compteur("serpapi")
        st.caption(f"Jusqu'à {limite} recherches SerpAPI (une par nouvelle entreprise ; les entreprises déjà vues "
                   f"sont en cache). Reste ce mois-ci selon le plafond de l'outil : {reste}.")

    if not lancer:
        return

    def liste(texte):
        return [x.strip() for x in texte.replace(";", ",").split(",") if x.strip()]

    args = argparse.Namespace(
        activite=activites, naf=liste(naf), ville=liste(villes), cp=[], departement=liste(departements),
        mots_cles=None, limite=int(limite), max_etablissements=None, sans_serpapi=not avec_serpapi,
        sans_brave=False, sans_pagespeed=not avec_pagespeed, rafraichir=rafraichir)
    if not (args.activite or args.naf):
        st.error("Choisis au moins une activité ou un code NAF.", icon=":material/error:")
        return
    if not (args.ville or args.departement):
        st.error("Indique au moins une ville ou un département.", icon=":material/error:")
        return

    barre = st.progress(0.0, text="Recherche des entreprises dans le registre…")
    apercu = st.empty()
    trouves = []

    def progression(i, total, p):
        trouves.append(p)
        barre.progress(i / total, text=f"{i}/{total} — {p['fiche']['enseigne'] or p['fiche']['nom']}")
        apercu.dataframe(en_tableau(trouves)[["Score", "Nom", "Ville", "Statut web", "URL"]],
                         column_config=CONFIG_COLONNES, width="stretch", hide_index=True)

    try:
        with st.spinner("Analyse en cours (OpenStreetMap peut prendre 30 s à 1 min)…"):
            prospects, chemin = prospect.executer(args, progression)
    except SystemExit as erreur:  # activité ou ville inconnue
        st.error(str(erreur), icon=":material/error:")
        return
    except ErreurAPI as erreur:
        st.error(f"Erreur d'API : {erreur}", icon=":material/error:")
        return

    barre.progress(1.0, text="Terminé")
    if not prospects:
        st.warning("Aucune entreprise trouvée avec ces critères.", icon=":material/search_off:")
        return
    chauds = sum(p["score"] >= 70 for p in prospects)
    st.success(f"{len(prospects)} entreprises analysées, dont {chauds} prospects chauds (score ≥ 70). "
               "Retrouve-les dans l'onglet **Prospects**.", icon=":material/task_alt:")
    st.download_button("Télécharger l'Excel de cette recherche", chemin.read_bytes(), file_name=chemin.name,
                       icon=":material/download:")


# --- Onglet : prospects -----------------------------------------------------------------------

def indicateurs(tableau):
    actifs = tableau[(tableau["Suivi"] != suivi.OPPOSITION) & (tableau["Franchise"] == "")]
    c1, c2, c3, c4 = st.columns(4, gap="large")
    c1.metric("Entreprises analysées", len(actifs), border=True)
    c2.metric("Prospects chauds (≥ 70)", int((actifs["Score"] >= 70).sum()), border=True)
    c3.metric("Sans site", int((actifs["Statut web"] == "Aucun site").sum()), border=True)
    c4.metric("À relancer", int((actifs["Suivi"] == "À relancer").sum()), border=True)


def onglet_prospects():
    prospects = charger_prospects()
    if not prospects:
        st.info("Aucune entreprise analysée pour l'instant : lance une recherche.", icon=":material/info:")
        return
    tableau = en_tableau(prospects)
    indicateurs(tableau)

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4, gap="large")
        villes = c1.multiselect("Ville", sorted(tableau["Ville"].unique()), placeholder="Toutes")
        activites = c2.multiselect("Activité", sorted(tableau["Activité"].unique()), placeholder="Toutes")
        statuts = c3.multiselect("Statut web", sorted(tableau["Statut web"].unique()), placeholder="Tous")
        etats = c4.multiselect("Suivi", suivi.ETATS, placeholder="Tous")
        c1, c2, c3 = st.columns([1, 2, 1], gap="large", vertical_alignment="bottom")
        score_min = c1.slider("Score minimum", 0, 100, 0, step=5)
        texte = c2.text_input("Recherche", placeholder="Nom, dirigeant, notes…", icon=":material/search:")
        masquer_opposition = c3.toggle("Masquer les oppositions", value=True)
        masquer_franchises = c3.toggle("Masquer les franchises", value=True)

    vue = tableau[tableau["Score"] >= score_min]
    if villes:
        vue = vue[vue["Ville"].isin(villes)]
    if activites:
        vue = vue[vue["Activité"].isin(activites)]
    if statuts:
        vue = vue[vue["Statut web"].isin(statuts)]
    if etats:
        vue = vue[vue["Suivi"].isin(etats)]
    if masquer_opposition:
        vue = vue[vue["Suivi"] != suivi.OPPOSITION]
    if masquer_franchises:
        vue = vue[vue["Franchise"] == ""]
    if texte:
        champs = vue["Nom"] + " " + vue["Dirigeant"] + " " + vue["Notes"]
        vue = vue[champs.str.contains(texte, case=False, regex=False)]

    st.caption(f"{len(vue)} entreprise(s) sur {len(tableau)}. Modifie les colonnes **Suivi** et **Notes**, "
               "puis clique sur Enregistrer.")
    modifie = st.data_editor(
        vue, column_config=CONFIG_COLONNES, width="stretch", height=560, key="editeur", hide_index=True,
        disabled=[c for c in vue.columns if c not in ("Suivi", "Notes")])

    c1, c2, _ = st.columns([1, 1, 3], gap="medium")
    if c1.button("Enregistrer le suivi", type="primary", icon=":material/save:", width="stretch"):
        changements = 0
        for siren, ligne in modifie.iterrows():
            avant = vue.loc[siren]
            if ligne["Suivi"] != avant["Suivi"] or ligne["Notes"] != avant["Notes"]:
                suivi.ecrire(siren, ligne["Suivi"], ligne["Notes"])
                if ligne["Suivi"] == suivi.OPPOSITION:
                    oppositions.ajouter(siren, ligne["Notes"] or "via l'interface")
                changements += 1
        st.toast(f"{changements} modification(s) enregistrée(s)", icon=":material/check_circle:")
        st.rerun()

    selection = [p for p in prospects if p["fiche"]["siren"] in set(vue.index)]
    if selection:
        chemin = DOSSIER_DATA / f"prospects_selection_{date.today().isoformat()}.xlsx"
        exporter(selection, chemin, "Sélection depuis l'interface")
        c2.download_button("Exporter la sélection", chemin.read_bytes(), file_name=chemin.name,
                           icon=":material/download:", width="stretch")


# --- Page -------------------------------------------------------------------------------------

st.html(STYLE)
st.title("Prospection")
st.caption("Entreprises sans site, avec seulement une page Facebook, ou avec un site cassé ou daté.")
onglet1, onglet2, onglet3 = st.tabs([":material/table_rows: Prospects", ":material/search: Nouvelle recherche",
                                     ":material/settings: Réglages"])
with onglet1:
    onglet_prospects()
with onglet2:
    onglet_recherche()
with onglet3:
    onglet_reglages()
