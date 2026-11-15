"""Étape 4 — Le rapport : un fichier Excel et une page web avec les captures d'écran, classés par score."""

from datetime import date
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import DOSSIER_DATA
from .jugement import CRITERES_DESIGN
from .outils import slug
from .potentiel import euros, retenu, texte_registre

INDEPENDANTE = "entreprise locale indépendante"


def trier(candidats):
    """Répartit les candidats : sites à refaire (par score), sans site, sites cassés, à voir, écartés, potentiel faible.

    Une entreprise dont le potentiel a été noté sous les seuils (métier où un site rapporte peu, ou entreprise
    sans signe de bonne santé) va dans « faible », qu'elle ait un site ou non.
    """
    groupes = {"prospects": [], "sans_site": [], "casses": [], "a_voir": [], "ecartes": [], "faible": []}
    for c in candidats:
        visite, verdict = c.get("visite") or {}, c.get("verdict")
        if verdict and ("note_design" not in verdict or "audit" not in visite):
            verdict = None  # jugé avant l'ajout du référentiel complet : à refaire
        if c.get("suivi") == "Opposition":
            continue
        if c.get("sans_site"):
            groupes["sans_site" if retenu(c) else "faible"].append(c)
        elif visite.get("etat") == "cassé":
            groupes["casses" if retenu(c) else "faible"].append(c)
        elif verdict and verdict["proprietaire"] == INDEPENDANTE:
            groupes["prospects" if retenu(c) else "faible"].append(c)
        elif verdict:
            groupes["ecartes"].append(c)
        else:
            groupes["a_voir"].append(c)
    groupes["prospects"].sort(key=lambda c: -c["verdict"]["score"])
    groupes["sans_site"].sort(key=lambda c: (-sum(potentiel(c)[k] or 0 for k in ("Intérêt d'un site", "Santé")),
                                             -(c.get("nb_avis") or 0)))
    return groupes


def potentiel(c):
    """Le potentiel commercial à plat : deux notes sur 5, la raison, et la fiche du registre des entreprises."""
    p = c.get("potentiel") or {}
    r = p.get("registre") or {}
    return {"Intérêt d'un site": p.get("interet_site"), "Santé": p.get("sante"), "Pourquoi": p.get("raison", ""),
            "Création": (r.get("creation") or "")[:4], "Effectif": r.get("effectif", ""),
            "Chiffre d'affaires": r.get("ca"), "Résultat": r.get("resultat"), "Année des comptes": r.get("annee") or "",
            "Registre": {"siret": "sûr (SIRET du site)", "nom": "par le nom, à vérifier"}.get(r.get("par"), "")}


def ligne_sans_site(c):
    return {"Entreprise": c["nom"], "Activité": c.get("activite"), **potentiel(c),
            "Accroche": (c.get("potentiel") or {}).get("accroche", ""), "Téléphone": c.get("telephone", ""),
            "Adresse": c.get("adresse", ""), "Note Google": c.get("note"), "Avis": c.get("nb_avis"),
            "Présence en ligne": c.get("url") or "aucune", "Ville": c["ville"], "Suivi": c.get("suivi", "Nouveau"),
            "Notes": c.get("notes", ""), "cle": c["cle"]}


def contact(c):
    """Meilleures coordonnées connues : celles de Google Maps ou d'OpenStreetMap, sinon celles du site."""
    relevees = (c.get("visite") or {}).get("coordonnees") or {}
    return {"telephone": c.get("telephone") or ", ".join(relevees.get("telephones", [])),
            "email": c.get("email") or ", ".join(relevees.get("emails", [])),
            "siret": relevees.get("siret", "")}


def notes(c):
    """Les quatre notes du référentiel, sur 100 : design (Claude), performance, SEO et GEO (mesurées)."""
    audit = (c.get("visite") or {}).get("audit") or {}
    return {"Design": (c.get("verdict") or {}).get("note_design"),
            "Performance": (audit.get("performance") or {}).get("note"),
            "SEO": (audit.get("seo") or {}).get("note"), "GEO": (audit.get("geo") or {}).get("note")}


def defauts_mesures(c):
    """Critères ratés de l'audit mesuré : {"Performance": [...], "SEO": [...], "GEO": [...]}."""
    audit = (c.get("visite") or {}).get("audit") or {}
    return {nom: (audit.get(cle_) or {}).get("defauts", [])
            for nom, cle_ in (("Performance", "performance"), ("SEO", "seo"), ("GEO", "geo"))}


def ligne(c):
    """Un prospect à plat, pour Excel et pour l'interface."""
    v, visite, coord = c.get("verdict") or {}, c.get("visite") or {}, contact(c)
    return {
        "Score": v.get("score"), "Entreprise": c["nom"], "Activité": v.get("activite") or c.get("activite"),
        **notes(c), **potentiel(c),
        "Niveau du site": v.get("niveau_site") or (f"cassé : {visite.get('motif')}" if visite.get("etat") == "cassé" else ""),
        "Fait maison": v.get("fait_maison", ""), "Problèmes": "\n".join(f"• {p}" for p in v.get("problemes", [])),
        "Défauts mesurés": "\n".join(f"[{nom}] {d}" for nom, liste in defauts_mesures(c).items() for d in liste),
        "Accroche": v.get("accroche", ""), "Résumé": v.get("resume", ""), "Site": visite.get("url_finale") or c["url"],
        "Téléphone": coord["telephone"], "E-mail": coord["email"], "Adresse": c.get("adresse", ""),
        "Note Google": c.get("note"), "Avis": c.get("nb_avis"), "Mobile": v.get("version_mobile", ""),
        "Constructeur": (visite.get("indices") or {}).get("constructeur", ""), "SIRET": coord["siret"],
        "Source": ", ".join(c.get("sources", [])), "Ville": c["ville"], "Suivi": c.get("suivi", "Nouveau"),
        "Notes": c.get("notes", ""), "cle": c["cle"],
    }


# --- Excel ------------------------------------------------------------------------------------

LARGEURS = {"Pourquoi": 50, "Présence en ligne": 30, "Intérêt d'un site": 10, "Santé": 8, "Défauts mesurés": 70, "Entreprise": 30, "Activité": 22, "Niveau du site": 22, "Problèmes": 60, "Accroche": 55, "Résumé": 55,
            "Site": 35, "Téléphone": 16, "E-mail": 28, "Adresse": 35, "Motif": 45}


def _feuille(classeur, titre, lignes):
    feuille = classeur.create_sheet(titre)
    if not lignes:
        feuille.append(["Rien dans cette catégorie."])
        return
    colonnes = [k for k in lignes[0] if k != "cle"]
    feuille.append(colonnes)
    for x in lignes:
        feuille.append([x[k] for k in colonnes])
    for i, colonne in enumerate(colonnes, start=1):
        cellule = feuille.cell(row=1, column=i)
        cellule.font, cellule.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F3A4F")
        feuille.column_dimensions[get_column_letter(i)].width = LARGEURS.get(colonne, 14)
    for rangee in feuille.iter_rows(min_row=2):
        for cellule in rangee:
            cellule.alignment = Alignment(wrap_text=True, vertical="top")
            if colonnes[cellule.column - 1] in ("Site", "Présence en ligne") and str(cellule.value or "").startswith("http"):
                cellule.hyperlink, cellule.font = cellule.value, Font(color="1A56DB", underline="single")
        score = rangee[0].value if colonnes[0] == "Score" else None
        if isinstance(score, int):
            rangee[0].fill = PatternFill("solid", fgColor="C8E6C9" if score >= 80 else "FFF3C4" if score >= 60 else "ECEFF1")
    feuille.freeze_panes = "C2"
    feuille.auto_filter.ref = feuille.dimensions


def excel(groupes, chemin):
    classeur = Workbook()
    classeur.remove(classeur.active)
    _feuille(classeur, "Site à refaire", [ligne(c) for c in groupes["prospects"]])
    _feuille(classeur, "Sans site", [ligne_sans_site(c) for c in groupes["sans_site"]])
    simples = lambda liste, motif: [{"Entreprise": c["nom"], "Activité": c.get("activite"), "Site": c["url"],  # noqa: E731
                                     "Motif": motif(c), "Téléphone": contact(c)["telephone"],
                                     "Adresse": c.get("adresse", ""), "Note Google": c.get("note"),
                                     "Avis": c.get("nb_avis")} for c in liste]
    _feuille(classeur, "Sites cassés", simples(groupes["casses"], lambda c: c["visite"]["motif"]))
    _feuille(classeur, "À voir à la main", simples(
        groupes["a_voir"], lambda c: (c.get("visite") or {}).get("motif") or "pas encore jugé (budget atteint)"))
    _feuille(classeur, "Écartés", simples(
        groupes["ecartes"], lambda c: f"{c['verdict']['proprietaire']} — {c['verdict']['resume']}"))
    _feuille(classeur, "Potentiel faible", [
        {"Entreprise": c["nom"], "Activité": c.get("activite"), "Site": c.get("url") or "aucun", **potentiel(c),
         "Score du site": (c.get("verdict") or {}).get("score"), "Téléphone": contact(c)["telephone"],
         "Adresse": c.get("adresse", ""), "Note Google": c.get("note"), "Avis": c.get("nb_avis")}
        for c in groupes["faible"]])
    classeur.save(chemin)


# --- Page web ---------------------------------------------------------------------------------

STYLE = """
:root{--fond:#f4f5f7;--carte:#fff;--texte:#1d2330;--doux:#5d6678;--trait:#e0e3ea;--accent:#3b5bdb}
@media(prefers-color-scheme:dark){:root{--fond:#16181d;--carte:#20242b;--texte:#e5e8ee;--doux:#98a1b3;--trait:#313743;--accent:#8ea2f5}}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 -apple-system,"Segoe UI",Inter,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:0 0 4px}h2{margin:40px 0 12px;font-size:19px}
.sous{color:var(--doux);margin:0 0 20px}.filtres{position:sticky;top:0;background:var(--fond);padding:10px 0;display:flex;gap:16px;flex-wrap:wrap;align-items:center;z-index:2;border-bottom:1px solid var(--trait)}
.filtres input[type=search]{flex:1;min-width:180px;padding:8px 10px;border:1px solid var(--trait);border-radius:8px;background:var(--carte);color:var(--texte);font:inherit}
.carte{background:var(--carte);border:1px solid var(--trait);border-radius:12px;padding:16px;margin:16px 0;display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);gap:18px}
@media(max-width:760px){.carte{grid-template-columns:1fr}}
.captures{display:flex;gap:8px;align-items:flex-start}.captures a{display:block;border:1px solid var(--trait);border-radius:6px;overflow:hidden;max-height:300px}
.captures img{display:block;width:100%}.captures .ordi{flex:3}.captures .mob{flex:1}
.tete{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.tete h3{margin:0;font-size:18px}
.score{font-weight:700;border-radius:8px;padding:4px 10px;color:#fff;background:#8792a5}.score.haut{background:#2f9e5b}.score.moyen{background:#c98a1b}
.puce{font-size:12.5px;border:1px solid var(--trait);border-radius:999px;padding:2px 9px;color:var(--doux)}
.infos{color:var(--doux);font-size:13.5px;margin:6px 0;overflow-wrap:anywhere}a{color:var(--accent)}ul{margin:8px 0;padding-left:20px}
.notes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0}.note{position:relative;border:1px solid var(--trait);border-radius:8px;padding:6px 8px 9px;overflow:hidden;font-size:12.5px;color:var(--doux)}
.note b{display:block;font-size:17px;color:var(--texte)}.note i{position:absolute;left:0;bottom:0;height:4px;background:#8792a5}.note i.bas{background:#d9534f}.note i.moy{background:#c98a1b}.note i.bon{background:#2f9e5b}
details{margin-top:10px;font-size:13.5px;color:var(--doux)}summary{cursor:pointer}
.accroche{border-left:3px solid var(--accent);padding:6px 12px;margin:10px 0 0;font-style:italic}
table{border-collapse:collapse;width:100%;background:var(--carte);border-radius:10px;overflow:hidden}td,th{padding:8px 10px;border-bottom:1px solid var(--trait);text-align:left;font-size:14px;overflow-wrap:anywhere;vertical-align:top}
.large{overflow-x:auto}.fiche{background:var(--carte);border:1px solid var(--trait);border-radius:12px;padding:14px 16px;margin:12px 0}
.potentiel{font-size:13.5px;color:var(--doux);margin:8px 0}.potentiel b{color:var(--texte)}nav{margin:0 0 14px;display:flex;gap:14px;flex-wrap:wrap}
"""
SCRIPT = """
const q=document.getElementById('q'),s=document.getElementById('s'),n=document.getElementById('n');
function filtrer(){let vus=0;document.querySelectorAll('.carte').forEach(c=>{const ok=+c.dataset.score>=+s.value&&c.textContent.toLowerCase().includes(q.value.toLowerCase());c.style.display=ok?'':'none';vus+=ok});
document.querySelectorAll('.fiche').forEach(c=>{c.style.display=c.textContent.toLowerCase().includes(q.value.toLowerCase())?'':'none'});
document.getElementById('seuil').textContent=s.value;n.textContent=vus}
q.oninput=s.oninput=filtrer;filtrer();
"""


def _potentiel(c):
    """La ligne « potentiel » d'une carte : les deux notes, la raison et ce que dit le registre."""
    p = c.get("potentiel")
    if not p:
        return ""
    registre = texte_registre(p.get("registre"))
    return (f"<p class='potentiel'>Intérêt d'un site <b>{p['interet_site']}/5</b> · santé de l'entreprise "
            f"<b>{p['sante']}/5</b> : {escape(p['raison'])}"
            + (f"<br>Registre des entreprises : {escape(registre)}" if registre else "") + "</p>")


def _fiche(c):
    """Une entreprise sans site."""
    e, p = escape, c.get("potentiel") or {}
    infos = [e(x) for x in (c.get("telephone"), c.get("adresse")) if x]
    if c.get("note"):
        infos.append(f"Google {c['note']} ★ ({c.get('nb_avis') or 0} avis)")
    infos.append(f'seule présence en ligne : <a href="{e(c["url"])}" target="_blank" rel="noopener">{e(c["domaine"])}</a>'
                 if c.get("url") else "aucun site sur sa fiche Google")
    return f"""<article class="fiche"><div class="tete"><h3>{e(c['nom'])}</h3><span class="infos">{e(c.get('activite') or '')}</span></div>
<div class="infos">{' · '.join(infos)}</div>{_potentiel(c)}
{f'<p class="accroche">{e(p["accroche"])}</p>' if p.get("accroche") else ''}</article>"""


def _carte(c):
    v, visite, coord, e = c["verdict"], c["visite"], contact(c), escape
    score = v["score"]
    images = "".join(f'<a class="{classe}" href="{e(visite[champ])}" target="_blank"><img loading="lazy" src="{e(visite[champ])}" alt=""></a>'
                     for classe, champ in (("ordi", "capture_ordinateur"), ("mob", "capture_mobile")) if visite.get(champ))
    infos = [f'<a href="{e(visite["url_finale"])}" target="_blank" rel="noopener">{e(c["domaine"])}</a>']
    infos += [e(x) for x in (coord["telephone"], coord["email"], c.get("adresse")) if x]
    if c.get("note"):
        infos.append(f"Google {c['note']} ★ ({c.get('nb_avis') or 0} avis)")
    puces = [v["niveau_site"], f"fait maison : {v['fait_maison']}", f"mobile : {v['version_mobile']}"]
    if visite["indices"].get("constructeur"):
        puces.append(visite["indices"]["constructeur"])
    couleur = lambda n: "bas" if n < 50 else "moy" if n < 75 else "bon"  # noqa: E731
    jauges = "".join(
        f'<div class="note"><span>{nom}</span><b>{"–" if n is None else n}</b>'
        f'<i class="{"" if n is None else couleur(n)}" style="width:{n or 0}%"></i></div>' for nom, n in notes(c).items())
    detail = "<p><b>Design</b> (noté par Claude, de 0 à 5) : " + " · ".join(
        f"{e(CRITERES_DESIGN[k])} {n}/5" for k, n in v["design"].items()) + "</p>"
    for nom, liste in defauts_mesures(c).items():
        if liste:
            detail += f"<p><b>{nom}</b>, critères ratés :</p><ul>{''.join(f'<li>{e(d)}</li>' for d in liste)}</ul>"
    return f"""<article class="carte" data-score="{score}">
<div class="captures">{images}</div>
<div><div class="tete"><span class="score {'haut' if score >= 80 else 'moyen' if score >= 60 else ''}">{score}</span>
<h3>{e(c['nom'])}</h3><span class="infos">{e(v['activite'])}</span></div>
<div class="infos">{' · '.join(infos)}</div>
<div>{' '.join(f'<span class="puce">{e(p)}</span>' for p in puces)}</div>
<div class="notes">{jauges}</div>{_potentiel(c)}
<p>{e(v['resume'])}</p><ul>{''.join(f'<li>{e(p)}</li>' for p in v['problemes'])}</ul>
<p class="accroche">{e(v['accroche'])}</p>
<details><summary>Détail du référentiel</summary>{detail}</details></div></article>"""


def _tableau(candidats, motif):
    if not candidats:
        return "<p class='sous'>Aucun.</p>"
    lignes = "".join(
        f"<tr><td>{escape(c['nom'])}</td><td><a href='{escape(c['url'])}' target='_blank' rel='noopener'>"
        f"{escape(c['domaine'])}</a></td><td>{escape(motif(c) or '')}</td><td>{escape(contact(c)['telephone'])}</td></tr>"
        for c in candidats)
    return f"<div class='large'><table><tr><th>Entreprise</th><th>Site</th><th>Motif</th><th>Téléphone</th></tr>{lignes}</table></div>"


def page_web(groupes, ville, chemin):
    p = groupes["prospects"]
    chauds = sum(1 for c in p if c["verdict"]["score"] >= 60)
    corps = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Prospects {escape(ville)}</title>
<style>{STYLE}</style></head><body><main>
<h1>Prospects à {escape(ville)}</h1>
<p class="sous">Rapport du {date.today().strftime('%d/%m/%Y')}. Seules figurent les entreprises dont le métier tire vraiment
parti d'un site et qui montrent des signes de bonne santé (avis Google, registre des entreprises) ; les
{len(groupes['faible'])} autres sont dans l'onglet « Potentiel faible » de l'Excel.</p>
<nav><a href="#refaire">Site à refaire ({len(p)}, dont {chauds} à 60 ou plus)</a>
<a href="#sans">Sans site ({len(groupes['sans_site'])})</a><a href="#casses">Sites cassés ({len(groupes['casses'])})</a></nav>
<div class="filtres"><input id="q" type="search" placeholder="Filtrer : nom, activité, problème…">
<span class="sous" style="margin:0">Notes sur 100 : design jugé par Claude sur 6 critères ; performance (mobile, 4G), SEO et GEO mesurés.</span>
<label>Score minimum <b id="seuil"></b> <input id="s" type="range" min="0" max="100" step="5" value="50"></label>
<span class="sous" style="margin:0"><b id="n"></b> affichés</span></div>
<h2 id="refaire">Ont un site à refaire ({len(p)})</h2>
{''.join(_carte(c) for c in p)}
<h2 id="sans">N'ont pas de site ({len(groupes['sans_site'])})</h2>
<p class="sous">Fiches Google Maps sans site, ou avec seulement une page Facebook, Instagram ou de plateforme. Vérifie
d'une recherche rapide avant d'appeler : une fiche Google peut simplement ne pas mentionner un site qui existe.</p>
{''.join(_fiche(c) for c in groupes['sans_site'])}
<h2 id="casses">Sites cassés ou disparus ({len(groupes['casses'])})</h2>
<p class="sous">L'entreprise annonce un site qui ne fonctionne plus : bon prétexte pour l'appeler.</p>
{_tableau(groupes['casses'], lambda c: c['visite']['motif'])}
<h2>À voir à la main ({len(groupes['a_voir'])})</h2>
{_tableau(groupes['a_voir'], lambda c: (c.get('visite') or {}).get('motif') or 'pas encore jugé (budget atteint)')}
<h2>Écartés ({len(groupes['ecartes'])})</h2>
{_tableau(groupes['ecartes'], lambda c: c['verdict']['proprietaire'])}
</main><script>{SCRIPT}</script></body></html>"""
    chemin.write_text(corps, encoding="utf-8")


def produire(candidats, ville):
    """Écrit data/<ville>/prospects.xlsx et data/<ville>/rapport.html. Renvoie (groupes, excel, page)."""
    dossier = DOSSIER_DATA / slug(ville)
    dossier.mkdir(parents=True, exist_ok=True)
    groupes = trier(candidats)
    excel(groupes, dossier / "prospects.xlsx")
    page_web(groupes, ville, dossier / "rapport.html")
    return groupes, dossier / "prospects.xlsx", dossier / "rapport.html"
