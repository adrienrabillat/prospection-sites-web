"""Étape 4a — Score de prospect sur 100 (pondération dans config.yaml, section « score »)."""

from datetime import date

from .config import CONFIG


def statut_court(statut):
    """« Site cassé (HTTP 404) » -> « Site cassé »."""
    return statut.split(" (")[0]


def calculer(fiche, site, analyse):
    regles = CONFIG["score"]
    if site.get("franchise"):  # franchise repérée dans le titre Google ou du site : pas un prospect
        return 0
    score = regles["statut"].get(statut_court(site["statut"]), 50)

    if analyse:
        score += sum(regles["signaux"].get(s, 0) for s in analyse["signaux"])
        score += regles["gamme"].get(analyse["gamme"], 0)
        if not analyse["rdv_en_ligne"]:
            score += regles["bonus"]["pas_de_rdv_en_ligne"]

    bonus = regles["bonus"]
    note, nb_avis = site["google"].get("note"), site["google"].get("nb_avis")
    if note and nb_avis and note >= bonus["note_google_min"] and nb_avis >= bonus["nb_avis_min"]:
        score += bonus["bonne_reputation"]
    if fiche["date_creation"] and int(fiche["date_creation"][:4]) >= date.today().year - bonus["creation_recente_annees"]:
        score += bonus["creation_recente"]
    return max(0, min(100, score))
