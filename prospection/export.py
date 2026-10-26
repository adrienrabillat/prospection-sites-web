"""Étape 4b — Export Excel : onglet Prospects (trié par score) et onglet Résumé."""

from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .score import statut_court

COLONNES = [  # (titre, largeur)
    ("Score", 7), ("Nom", 30), ("Enseigne", 24), ("Activité", 26), ("Adresse", 36), ("CP", 7), ("Ville", 16),
    ("Téléphone", 16), ("E-mail", 26), ("Dirigeant", 26), ("Date de création", 12), ("Effectif", 16),
    ("Statut web", 26), ("URL", 32), ("Source du site", 18), ("Confiance", 10), ("CMS", 16), ("Version", 9),
    ("HTTPS", 7), ("Mobile", 7), ("Copyright", 9), ("PageSpeed", 10), ("Note Google", 8), ("Nb avis", 8),
    ("SIREN", 11), ("SIRET", 16), ("Date d'analyse", 12), ("Signaux de site daté", 40), ("Thème / builder", 22),
    ("RDV en ligne", 18), ("Formulaire", 10), ("Preuve du site", 30), ("Franchise / réseau", 14), ("Opposition", 12),
    ("Suivi", 14), ("Notes", 40),
]

LIBELLES_SIGNAUX = {
    "pas_https": "pas de HTTPS", "pas_mobile": "pas adapté mobile", "copyright_ancien": "copyright ancien",
    "jquery_ancien": "jQuery ancien", "flash": "Flash", "tableaux": "mise en page en tableaux",
    "pas_de_title": "pas de <title>", "pas_de_meta_description": "pas de meta description",
    "lent": "réponse lente", "pagespeed_mauvais": "PageSpeed mauvais",
}

ENTETE = PatternFill("solid", fgColor="1F2937")
CHAUD = PatternFill("solid", fgColor="F8B4B4")
TIEDE = PatternFill("solid", fgColor="FCD9A8")
FROID = PatternFill("solid", fgColor="DCE6F2")
LIEN = Font(color="1D4ED8", underline="single")
GRIS = Font(color="9CA3AF", strike=True)


def oui_non(valeur):
    return "" if valeur is None else ("Oui" if valeur else "Non")


def ligne_excel(p):
    """Transforme un prospect (dict produit par prospect.py) en valeurs dans l'ordre des colonnes."""
    f, s, a = p["fiche"], p["site"], p.get("analyse") or {}
    g = s.get("google") or {}
    theme = " / ".join(x for x in (a.get("theme"), a.get("page_builder")) if x)
    return [
        p["score"], f["nom"], f["enseigne"], f"{f['libelle_naf']} ({f['naf']})", f["adresse"], f["code_postal"],
        f["ville"], s.get("telephone") or g.get("telephone") or "", a.get("email", ""), f["dirigeants"],
        f["date_creation"], f["tranche_effectif"], s["statut"], s["url"], s["source"], s["confiance"],
        a.get("cms", ""), a.get("version", ""), oui_non(a.get("https")), oui_non(a.get("mobile")),
        a.get("copyright") or "", a.get("pagespeed") if a.get("pagespeed") is not None else "",
        g.get("note") or "", g.get("nb_avis") or "", f["siren"], f.get("siret_local") or f.get("siret_siege") or "",
        p["date_analyse"],
        ", ".join(LIBELLES_SIGNAUX.get(x, x) for x in a.get("signaux", [])), theme,
        a.get("rdv_en_ligne", ""), oui_non(a.get("formulaire")) if a else "", s.get("preuve", ""),
        (s.get("franchise") or "").upper(),
        "OUI — ne pas contacter" if p["opposition"] else "", p.get("suivi", ""), p.get("notes", ""),
    ]


def _onglet_prospects(feuille, prospects):
    feuille.append([titre for titre, _ in COLONNES])
    for i, (_, largeur) in enumerate(COLONNES, start=1):
        cellule = feuille.cell(row=1, column=i)
        cellule.font, cellule.fill = Font(bold=True, color="FFFFFF"), ENTETE
        cellule.alignment = Alignment(wrap_text=True, vertical="center")
        feuille.column_dimensions[get_column_letter(i)].width = largeur
    index = {titre: i for i, (titre, _) in enumerate(COLONNES, start=1)}

    for p in prospects:
        feuille.append(ligne_excel(p))
        rang = feuille.max_row
        score = feuille.cell(row=rang, column=index["Score"])
        score.fill = CHAUD if p["score"] >= 70 else TIEDE if p["score"] >= 45 else FROID
        score.font = Font(bold=True)
        url = feuille.cell(row=rang, column=index["URL"])
        if url.value:
            url.hyperlink, url.font = url.value, LIEN
        siren = feuille.cell(row=rang, column=index["SIREN"])
        siren.hyperlink = f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren.value}"
        siren.font = LIEN
        if p["opposition"]:
            for cellule in feuille[rang]:
                cellule.font = GRIS

    feuille.freeze_panes = "C2"
    feuille.auto_filter.ref = feuille.dimensions
    feuille.row_dimensions[1].height = 32


def _onglet_resume(feuille, prospects, criteres):
    gras = Font(bold=True)
    feuille.append(["Recherche", criteres])
    feuille.append(["Entreprises analysées", len(prospects)])
    feuille.append([])

    feuille.append(["Statut web", "Nombre"])
    for cellule in feuille[feuille.max_row]:
        cellule.font = gras
    for statut, nombre in Counter(statut_court(p["site"]["statut"]) for p in prospects).most_common():
        feuille.append([statut, nombre])
    feuille.append([])

    feuille.append(["CMS (sites actifs)", "Nombre"])
    for cellule in feuille[feuille.max_row]:
        cellule.font = gras
    cms = Counter(p["analyse"]["cms"] for p in prospects if p.get("analyse"))
    for nom, nombre in cms.most_common() or [("—", 0)]:
        feuille.append([nom, nombre])
    feuille.append([])

    feuille.append(["Top 20", "Score", "Statut web", "Ville", "Téléphone", "URL"])
    for cellule in feuille[feuille.max_row]:
        cellule.font = gras
    for p in [p for p in prospects if not p["opposition"]][:20]:
        s = p["site"]
        feuille.append([p["fiche"]["enseigne"] or p["fiche"]["nom"], p["score"], s["statut"], p["fiche"]["ville"],
                        s.get("telephone") or (s.get("google") or {}).get("telephone") or "", s["url"]])
    for colonne, largeur in zip("ABCDEF", (36, 10, 28, 18, 18, 40)):
        feuille.column_dimensions[colonne].width = largeur


def exporter(prospects, chemin, criteres):
    prospects = sorted(prospects, key=lambda p: (p["opposition"], -p["score"]))
    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Prospects"
    _onglet_prospects(feuille, prospects)
    _onglet_resume(classeur.create_sheet("Résumé"), prospects, criteres)
    chemin.parent.mkdir(exist_ok=True)
    classeur.save(chemin)
    return chemin
