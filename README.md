# Prospection : les entreprises d'une ville dont le site est à refaire

Tu donnes une ville. L'outil trouve les entreprises indépendantes qui ont **déjà un site, mais un site raté** : fait par le patron lui-même, amateur ou très daté. Ce sont celles qui ont déjà voulu un site et à qui il manque quelqu'un pour le faire correctement. Chaque site est visité dans un vrai navigateur, puis **Claude regarde les captures d'écran** (ordinateur et mobile) et rend un verdict : score, défauts visibles, accroche pour le premier contact.

```bash
.venv/bin/python prospect.py "Clichy"
```

Il relève aussi les entreprises **sans site** (fiche Google Maps sans site, ou avec seulement une page Facebook, Instagram, Doctolib…). Dans les deux cas, seules sont gardées celles **dont le métier tire vraiment parti d'un site et qui montrent des signes de bonne santé**.

Résultat dans `data/clichy/` : `rapport.html` (les prospects avec leurs captures, à ouvrir dans le navigateur) et `prospects.xlsx`.

> Les prospects (`data/`), la base (`prospection.sqlite`) et les clés (`.env`) restent en local et ne sont pas versionnés.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium     # le navigateur qui visite les sites
cp .env.example .env                      # puis remplir ANTHROPIC_API_KEY (et SERPAPI_KEY)
```

## Utilisation

```bash
.venv/bin/python prospect.py "Clichy"                 # une ville, budget par défaut (20 $)
.venv/bin/python prospect.py "Levallois-Perret" --budget 8
.venv/bin/python prospect.py "Clichy" --limite 20     # essai rapide sur 20 sites
```

| Option | Rôle |
|---|---|
| `--budget N` | Dépense Anthropic maximale pour ce lancement, en dollars |
| `--limite N` | Ne traite que N sites (pour essayer) |
| `--sans-google` | N'utilise pas le quota Google Maps |
| `--visites-seulement` | Trouve et visite les sites sans les faire juger (gratuit, sans clé Anthropic) |
| `--refaire` | Revisite et rejuge les sites déjà traités |

Compte 30 à 45 minutes et 15 à 20 $ pour une ville de 60 000 habitants (environ 370 sites). Tu peux interrompre (Ctrl+C) : **relancer la même commande reprend où l'on s'était arrêté**, sans revisiter ni repayer ce qui est fait. Si le budget s'arrête avant la fin, les sites qui ont le plus l'air faits maison sont jugés en premier.

**Interface** : double-clique sur `lancer.command`, ou `.venv/bin/streamlit run app.py`. Trois onglets : les prospects de toutes les villes (filtres, captures, suivi commercial et notes), le lancement d'une nouvelle ville, les réglages (clés, dépense).

## Comment ça marche

**1. Trouver les entreprises qui ont un site.** On part des sites réels, pas du registre des entreprises : chaque source donne directement le lien « entreprise → son site ».
- **OpenStreetMap** (gratuit) : tous les lieux de la commune qui ont un site.
- **Google Maps** via SerpAPI : une recherche par métier (liste `metiers` de `config.yaml`, 46 par défaut), 20 entreprises chacune, avec site, téléphone, note et nombre d'avis. Seules les entreprises dont l'adresse est dans la ville sont gardées. Le plan gratuit donne 250 recherches par mois, soit **5 villes par mois**.
- **Secours** si Google Maps n'est pas disponible (pas de clé, quota épuisé) : Claude cherche les entreprises de chaque métier sur le web. C'est nettement moins productif (2 ou 3 sites par métier pour environ 0,15 $) : mieux vaut attendre le quota du mois suivant ou prendre un plan SerpAPI.

Sont écartés sans rien dépenser : réseaux sociaux, annuaires et plateformes, administrations, chaînes et franchises (marque connue d'OpenStreetMap, liste `enseignes`, domaine présent sur plus de deux lieux).

**2. Visiter chaque site** dans Chromium, comme un visiteur : capture de l'accueil sur ordinateur et sur mobile (bandeau de cookies fermé), texte affiché, indices techniques (constructeur de site, sous-domaine gratuit, adaptation mobile, année du copyright, e-mail en gmail…), coordonnées relevées sur l'accueil, les mentions légales et la page contact. Le chargement sur mobile est chronométré. Au plus quatre pages par site, plus `robots.txt`, `sitemap.xml` et `llms.txt`. Un site qui ne répond pas est réessayé avant d'être classé « cassé » ; si le lien de la fiche Google pointe sur une page disparue, l'accueil du site est visité à la place.

**3. Noter selon le référentiel** (détail ci-dessous), puis juger. Claude (`claude-opus-5-5`) reçoit les deux captures, le texte, les indices et l'audit mesuré, et rend :
- à qui appartient le site (entreprise locale indépendante, chaîne, administration, plateforme…) ;
- le niveau du site (fait maison ou amateur, daté, correct mais perfectible, professionnel et récent, vide ou en construction) et la probabilité qu'il soit fait maison, avec les indices ;
- les six notes de design ;
- 3 à 6 **défauts concrets** (apparence, vitesse, SEO, GEO), chiffres à l'appui ;
- un **score de 0 à 100** (80+ : la refonte se vend d'elle-même ; 60 à 79 : facile à justifier) ;
- une **accroche** pour le premier contact.

**4. Noter le potentiel commercial** (`prospection/potentiel.py`), pour toutes les entreprises, avec ou sans site. Deux notes de 0 à 5 données par Claude (`claude-sonnet-5-5`, environ 0,03 $ pour 20 entreprises) :
- **intérêt d'un site** : selon le métier (les clients cherchent-ils en ligne, que vaut un client ?). Un couvreur ou un restaurant où l'on réserve : 5. Un tabac ou un pressing de quartier : 1 à 3 ;
- **santé de l'entreprise** : note et nombre d'avis Google, et fiche du **registre des entreprises** de l'État (API gratuite) : année de création, effectif, chiffre d'affaires et résultat quand ils sont publiés. La fiche est sûre quand le SIRET figure sur le site ; sinon elle est cherchée par le nom dans la commune, gardée seulement si les noms se ressemblent nettement, et marquée « à vérifier ». Sans aucune donnée, la santé vaut 2.

Seuils dans `config.yaml` (`potentiel.interet_min: 4`, `potentiel.sante_min: 3`). Ce qui est en dessous n'apparaît pas dans le rapport et va dans l'onglet « Potentiel faible » de l'Excel.

**5. Rapport.** `rapport.html` (sites à refaire avec captures, puis entreprises sans site, filtre par score et par mot) et `prospects.xlsx` avec six onglets : Site à refaire, Sans site, Sites cassés (bon prétexte pour appeler), À voir à la main (sites qui bloquent les robots, ou pas encore jugés), Écartés, Potentiel faible.

## Le référentiel : sur quoi un site est jugé

Quatre notes sur 100. Trois sont **mesurées par des règles fixes** (`prospection/audit.py`) : le même site obtient toujours la même note, et chaque point perdu est expliqué dans le rapport (« Détail du référentiel »). La quatrième, le design, est donnée par Claude sur une grille.

| Note | Comment | Critères |
|---|---|---|
| **Design** | Claude, d'après les captures ordinateur et mobile, six critères notés de 0 à 5 | Mise en page · typographie et couleurs · images et logo · contenu et crédibilité · mobile · incitation à l'action |
| **Performance** | Chargement réel dans Chromium, dans les conditions du test mobile de Google PageSpeed (4G lente, processeur ralenti 4 fois) | Affichage du contenu principal, LCP (40 pts, bon ≤ 2,5 s) · poids de la page (20, ≤ 1,5 Mo) · réponse du serveur, TTFB (15, ≤ 0,8 s) · stabilité de la mise en page, CLS (15, ≤ 0,1) · nombre de requêtes (10, ≤ 60) |
| **SEO** | Lecture du code de l'accueil, de `robots.txt` et de `sitemap.xml` | Titre (12) · description (10) · H1 unique (10) · ville dans le titre ou le H1 (10) · 250 mots au moins (10) · HTTPS (8) · balise mobile (8) · textes alternatifs des images (8) · pas de `noindex` (6) · sitemap (5) · langue (4) · adresse canonique (4) · robots.txt (3) |
| **GEO** | Ce qu'un moteur à IA (ChatGPT, Perplexity, Google AI Overviews) peut lire et citer | Données structurées schema.org (20) · fiche d'entreprise structurée avec coordonnées (15) · contenu lisible sans JavaScript (20) · robots d'IA non bloqués par robots.txt (15) · contenu en questions-réponses (10) · horaires, tarifs, adresse (5 chacun) · `llms.txt` (5) |

Les seuils LCP, CLS et TTFB sont ceux de Google (Core Web Vitals). Le GEO n'a pas de norme officielle : la grille reprend ce qui rend un site lisible et citable par les IA, et le poids de chaque critère se change dans `audit.py`.

Le **score** final du prospect est donné par Claude à partir de tout cela : le design d'abord, puis les trois notes mesurées, et l'intérêt commercial (entreprise indépendante, active, bien notée). Il sert à classer ; les quatre notes servent à argumenter.

## Coût

Environ **0,05 $ par site jugé** (deux images, le texte, le verdict). La dépense réelle est comptée d'après les tokens facturés, enregistrée dans la base et affichée à chaque lancement. Deux plafonds dans `config.yaml` : `budget.par_ville_usd` (20 $) et `budget.total_usd` (100 $, tous lancements confondus). Pour diviser le coût par deux, mets `ia.modele: claude-sonnet-5-5`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `prospect.py` | La commande |
| `app.py`, `lancer.command` | L'interface |
| `prospection/collecte.py` | Étape 1 : OpenStreetMap, Google Maps, secours par Claude |
| `prospection/visite.py` | Étape 2 : navigateur, captures, indices, coordonnées |
| `prospection/audit.py` | Le référentiel mesuré : performance, SEO, GEO |
| `prospection/jugement.py` | Étape 3 : grille de design et verdict de Claude, budget |
| `prospection/potentiel.py` | Étape 4 : intérêt d'un site pour le métier, santé de l'entreprise, registre |
| `prospection/rapport.py` | Étape 5 : page web et Excel |
| `prospection/base.py` | Base SQLite : candidats, dépenses, quotas, suivi |
| `config.yaml` | Budgets, modèle, métiers cherchés, exclusions |
| `empreintes.yaml` | Empreintes des constructeurs de sites et des pages parking |
| `prospection.sqlite` | Tout ce qui a été trouvé et payé, et ton suivi : **ne le supprime pas** |

## RGPD et règles de la prospection B2B

L'outil ne traite que des informations publiées par les entreprises elles-mêmes (leur site, leur fiche Google, OpenStreetMap). Les noms de personnes et les entreprises individuelles restent des données personnelles : le RGPD s'applique.

- **Base légale** : intérêt légitime (proposer un service en rapport avec l'activité de l'entreprise).
- **Ce qui part chez Anthropic** : le nom, l'activité, l'adresse et le site de l'entreprise, avec les captures et le texte de sa page d'accueil. Uniquement des pages publiques.
- **Information** : dès le premier contact, dis qui tu es, d'où viennent les coordonnées (« votre site », « votre fiche Google ») et comment s'opposer.
- **Opposition** : quand une entreprise refuse, passe-la en « Opposition » dans l'interface. Elle disparaît des rapports et n'est plus jamais analysée.
- **E-mail B2B** (art. L34-5 du CPCE, doctrine CNIL) : pas de consentement préalable si le message est en rapport avec la profession du destinataire. Chaque e-mail identifie l'expéditeur et contient un moyen simple de se désinscrire. Préfère les adresses génériques (`contact@`).
- **Téléphone** : privilégie la ligne de l'entreprise. Depuis le 11 août 2026, le démarchage téléphonique des particuliers exige leur accord préalable ; pour un entrepreneur individuel joint sur son mobile personnel, la frontière est floue.
- **Conservation** : supprime les prospects sans réponse au bout de 3 ans. Ne revends ni ne partage ces fichiers.

## Limites connues

- Une entreprise absente d'OpenStreetMap et des 20 premiers résultats Google Maps de son métier n'est pas vue. Pour creuser, passe `google_maps.pages_par_metier` à 2 ou ajoute des métiers.
- Le jugement et l'audit portent sur la page d'accueil : un site dont seules les pages intérieures sont ratées peut passer pour correct.
- La performance est mesurée une fois, depuis ton ordinateur, pendant que d'autres sites se chargent : elle est indicative, à quelques dixièmes de seconde près. Pour un chiffre à montrer au client, refais le test sur PageSpeed Insights.
- Le SEO mesuré est le SEO « sur la page ». Le classement réel dans Google et la présence réelle dans les réponses des IA ne sont pas testés.
- Les sites qui bloquent les robots (HTTP 403) ne sont pas jugés : ils sont listés dans « À voir à la main ».
- « Sans site » veut dire « pas de site sur la fiche Google Maps » : vérifie d'une recherche avant d'appeler. Seules les entreprises sorties dans les 20 premiers résultats de leur métier sont vues.
- La santé d'une entreprise est estimée, pas prouvée : la plupart des petites entreprises ne publient pas leurs comptes, et une entreprise trouvée seulement sur OpenStreetMap (sans avis Google) dont le SIRET n'est pas sur le site est écartée faute de données. Elle reste dans l'onglet « Potentiel faible ».
