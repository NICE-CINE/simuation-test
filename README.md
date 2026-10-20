# Festival BLE Mesh Simulator

## TODO

Limites connues du simulateur, a traiter dans cet ordre de priorite :

- [ ] **Participation reelle** : tout le monde a l'app et elle tourne au
  premier plan. A modeliser : taux d'adoption (une partie seulement des
  festivaliers est un noeud, les autres ne font qu'attenuer le signal ;
  l'app est Android uniquement, les possesseurs d'iPhone n'en font donc
  pas partie), gel de l'app ecran eteint sur EMUI (Huawei/Honor, voir
  `docs/energie/consommation.md` ; Samsung avec les reglages d'usine pas
  encore teste).
- [ ] **Radio** (mesures du 16 oct., `docs/radio/mesures.md`) : les 30 m
  du telephone sont mesures avec seulement 5 personnes groupees devant
  l'ancre, une borne haute pour un festival. A faire :
  - **mesurer dans une vraie foule**, les corps repartis sur tout le trajet
    (sortie d'amphi, file de cantine, concert) : c'est la mesure qui manque
    le plus, l'exposant 2,7 en foule est estime (plein air : 1,8) ;
  - ajouter une attenuation par les corps qui croit avec la densite de la
    foule (l'exposant est le meme a 3 m2/personne et sur un site vide) ;
  - la **variabilite** : ~11 dB d'ecart a 1 m entre deux passes (orientation
    du telephone, terrain), un effet lent ; le shadowing actuel (4 dB) est
    tire independamment a chaque tick et par sens. Il faudrait un decalage
    fixe par telephone et un shadowing correle dans le temps et reciproque
    par paire ;
  - le **lien fantome** : hors de portee, Nearby ne declare parfois jamais la
    coupure (rien en 300 s) ; les messages confies au lien attendent et
    arrivent d'un coup au retour, au lieu de passer par un autre voisin. Le
    simulateur ferme toujours le lien des que la paire sort de portee ;
  - ne plus tronquer la portee (un fading favorable ne prolonge jamais un
    lien au-dela du rayon deterministe, alors qu'en plein air le lien tient
    en dernier recours jusqu'a 100-150 m) ;
  - la portee des bornes (60 m) n'est pas mesuree.
- [ ] **Valeurs estimees a mesurer** : cout energetique d'une connexion et
  de chaque connexion en plus (`connection_setup_mah`,
  `extra_connection_current_ma`), fermeture d'une connexion inactive
  (`connection_idle_timeout_s`), taille des annonces bitchat et des
  beacons ECO-SF, tous les reglages de `GroupConfig` (sorties, attente au
  rendez-vous, distance a laquelle on reconnait son groupe, probabilite
  qu'une sortie scinde le groupe en deux), le programme `--schedule`
  (`ScheduleConfig` : sets d'1 h, scene x3, 30 % de pauses coupees), le nombre
  d'amis venus a part (`SocialConfig.outside_friends_range`, 0 a 2), le
  rythme des messages pendant un rendez-vous rate
  (`TrafficConfig.lost_messages_per_hour`, 6/h), connexions simultanees
  (`max_concurrent_links`, 6) et debit avec plusieurs voisins (il faut 3
  telephones ou plus), delai de connexion en distribution plutot que les
  12 s fixes (26 a 80 s mesures loin de l'ancre), taille d'un resume
  (`summary_id_bytes`, 4 o) ; liste et priorites radio dans
  `docs/radio/mesures.md` §7.
- [ ] **Oracles restants** : `band_fanout` lit la position GPS des voisins
  sans annonce radio ; `band_fanout` et `eco_sf` consultent le buffer
  d'un voisin dans `on_tick` avant toute connexion ; `band_fanout` lit
  aussi « ce voisin a croise le destinataire » avant toute connexion pour
  lui donner un lien (la table n'est payee qu'une fois connecte ; mesure
  oct. 2026 sans ces deux lectures : livraison inchangee, +56 % de latence
  en zone dense) ; les tables des
  algorithmes sont facturees une fois par connexion mais lues a jour
  ensuite ; la joignabilite bitchat ignore les pertes de ses annonces.
- [ ] **Validation** : comparer les durees de contact, les temps entre
  contacts et le nombre de voisins a des traces reelles (Infocom/Haggle,
  etudes de foule) ; rien n'est valide aujourd'hui.
- [ ] **Resultats chiffres des pages `docs/algorithmes/`** : mesures
  anterieures au recalage d'octobre 2026 (connexions, canal, ACK payes,
  groupes, chauffe), a refaire.

Simulateur SimPy de messagerie opportuniste (mesh MANET) via Bluetooth
Low Energy entre les participants d'un festival.

## Installation

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

## Lancer une simulation

    python main.py

Le rapport est affiche dans le terminal et archive dans `archives/` :
`<date>_<heure>_<algo>.txt` (rapport) + `.json` du meme nom (arguments
CLI et `SimulationConfig` complete, pour pouvoir rejouer le run), ex.
`archives/2026-09-29_15-03-26_spray_wait.txt`.

### Options CLI

    python main.py --routing epidemic --beacons 6 --duration 3600 \
        --num-festivaliers 200 --seed 42

`python main.py --help` liste les options ci-dessous (avec leurs valeurs par
defaut) et les autres commandes ; `python main.py --help-all` affiche en plus
l'aide complete de chaque script (`compare_algorithms.py` et les deux
balayages).

Options disponibles :
- `--routing` : `epidemic` (defaut), `spray_wait`, `prophet`,
  `beacon_priority`, `dasfv`, `gossip_a`, `bubble_f`, `managed_flood`, `tide`, `tide_g`, `tide_g2`, `fresh_spray`, `geo_spray_focus`, `eco_sf`, `band_fanout`, `bitchat` ou `horizon` (un seul choix a la fois, pas de `|`).
  `band_fanout` n'a pas d'option dediee : `main.py` le lance avec ses
  defauts (`fanout=3`, `max_hops=4`, bande 40-60 %, purge activee) et
  `--seed` pour le tirage des relais ; pour faire varier ses parametres,
  voir "Balayer les variantes de band_fanout"
- `--mobility` : `random_waypoint` (defaut), `poi` (les festivaliers
  se repartissent entre scenes, bars et entree, voir plus bas) ou `group`
  (comme `poi`, mais les groupes d'amis se deplacent ensemble, voir plus bas)
- `--size` : `small`, `medium`, `large` ou `extra-large` (4 000 / 10 000 /
  30 000 / 60 000 festivaliers sur 12 000 / 30 000 / 90 000 / 180 000 m2,
  soit ~3 m2 par personne, ratio 1,4:1). Fixe aussi la repartition de la
  foule (70 % du public cible 15 % de la surface, voir `presets.py`) et
  active `--mobility group` par defaut ; refuse un `--num-festivaliers`
  different. Disponible aussi dans `compare_algorithms.py` (qui accepte
  plusieurs tailles, voir "Comparer les algorithmes") et
  `sweep_fresh_spray_tokens.py`. Sans `--size`, le site reste 700x500 m,
  4 000 festivaliers. La part mesuree dans la zone dense est un peu sous
  70 % (~67 % small, ~63 % large) : les gens en transit sont hors zone dense.
- `--beacons N` : nombre de bornes (0 = desactivees, defaut)
- `--beacon-placement` : `grid` (defaut) ou `manual`
- `--duration`, `--num-festivaliers`, `--seed`
- `--archive-dir DOSSIER` : dossier d'archive (defaut `archives`)
- `--output CHEMIN` : copie optionnelle du rapport, en plus de l'archive
- `--spray-initial-copies` : propre a `spray_wait` (defaut 8)
- `--replay-html` : ecrit un replay de la simulation dans
  `<archive-dir>/replay/`, sous `<date>_<algo>.html` + `<date>_<algo>.data.js`
  (voir "Visualisation / replay" plus bas)
- `--replay-frame-step S` : une position tous les S secondes simulees (defaut 5)
- `--replay-max-messages N` : nombre de messages dont tous les relais sont
  gardes (defaut 100) ; les autres messages livres ne gardent que leur livraison
- `--reply-probability P` : probabilite qu'un message livre recoive une
  reponse du destinataire apres 20 a 180 s (defaut 0, pas de reponses) ;
  necessaire pour que `tide_g` ait des indices de position
- `--followup-probability P` : probabilite qu'un message soit suivi d'une
  relance au meme destinataire apres 10 a 120 s (defaut 0, pas de rafales)
- `--gps-fix-failure P` : probabilite qu'un fix GPS echoue (defaut 0)
- `--random-charge` : charge de depart tiree par telephone (graine du run)
  au lieu de 100 % : 50 % des gens entre 80 et 100 %, 30 % entre 50 et 80,
  12 % entre 30 et 50, 8 % entre 5 et 30 (voir `docs/energie/consommation.md`)
- `--no-outside-friends` : pas d'amis venus a part, les amis sont
  exactement le groupe (voir "Destinataire : un ami" plus bas)
- `--no-lost-messages` : pas de messages en plus pendant un rendez-vous
  rate (voir "Messages de perdu" plus bas)
- `--schedule` : programme du festival (`poi` et `group`), concerts d'1 h
  alternes entre les deux scenes, la scene qui joue attire 3 fois plus et
  30 % des gens en pause partent au debut de chaque concert (desactive par
  defaut, voir `docs/mobilite/poi.md`)
- `--churn`, `--churn-arrival-window-s LO HI`, `--churn-session-duration-s LO HI` :
  arrivees/departs echelonnes des festivaliers (voir "Churn" plus bas)
- Raccourcis vers `--set`, pour les reglages qu'on fait varier le plus :
  - `--no-gps-noise` : GPS exact (defaut : bruit de 5 m)
  - `--no-shadowing` : radio deterministe, sans variation aleatoire du
    signal (defaut 4 dB, telephones et bornes)
  - `--messages-per-hour LO HI` : rythme d'envoi de chaque personne
    (defaut 0 4), le levier principal de la charge
  - `--message-ttl S` : duree de vie d'un message (defaut 1800 s)
  - `--max-links N` : connexions simultanees par telephone (defaut 6)
  - `--phone-tx-power DBM` : puissance d'emission, donc portee des
    telephones (defaut -10 dBm = 30 m ; -18 = 15 m, -15 = 20 m, -6 = 43 m,
    0 = 71 m). 30 m est une borne haute mesuree pour une foule
    (`docs/radio/mesures.md`) : comparer aussi a 15 et 20 m
- `--set CHEMIN=VALEUR` (repetable) : change n'importe quel reglage de
  `SimulationConfig` (voir ci-dessous), apres les raccourcis

### Tout regler avec `--set`

Chaque champ de `SimulationConfig` (`src/festival_ble_sim/config.py`) se
change depuis la ligne de commande, en suivant son chemin :

    python main.py --set traffic.message_ttl_s=900 \
        --set mobility.group.split_probability=0.5 \
        --set social.outside_friends_range=0,4 \
        --set ble.phone_radio.shadowing_std_db=0 --set churn.enabled=True

Valeurs : nombres, `True`/`False`, `None`, paires `a,b` ; le reste est lu
comme du texte (`--set beacons.placement=manual`). Un chemin inconnu est
refuse en listant les champs possibles, une valeur interdite par les
verifications de la config. Les `--set` s'appliquent apres les autres
options, et `--cooldown` (s'il n'est pas donne) suit un TTL change. Ils
sont archives dans le `.json` du run avec la config finale.
`compare_algorithms.py` et les deux balayages refusent `--set beacons.count`
(le nombre de bornes se regle avec `--beacon-count`, plus `--with-beacons`
pour `compare_algorithms.py`, qui sinon tourne sans bornes). Module :
`festival_ble_sim/overrides.py`.

**Options communes aux trois scripts** (`compare_algorithms.py`,
`sweep_band_fanout.py`, `sweep_fresh_spray_tokens.py`, via
`compare_algorithms.add_run_arguments`) : `--cooldown`, `--warmup`,
`--followup-probability`, `--gps-fix-failure`, `--random-charge`,
`--no-outside-friends`, `--no-lost-messages`, `--schedule`, `--churn`
(fenetres par `--set churn.arrival_window_s=LO,HI` et
`churn.session_duration_range_s=LO,HI`), les six raccourcis et `--set`.

## Comparer les algorithmes

    python scripts/compare_algorithms.py --seed 42 --duration 3600 \
        --num-festivaliers 200 [--with-beacons --beacon-count 6] --workers 2 [--csv comparaison.csv] \
        [--mobility poi] [--reply-probability 0.5] [--followup-probability 0.5] [--gps-fix-failure 0.1] \
        [--random-charge] [--no-outside-friends] [--no-lost-messages] [--schedule] [--churn] \
        [--no-gps-noise] [--max-links 4] [--set traffic.message_ttl_s=900 ...]

Lance automatiquement la matrice {epidemic, spray_wait, prophet,
beacon_priority, dasfv, gossip_a, bubble_f, managed_flood, tide, tide_g, tide_g2, fresh_spray, geo_spray_focus, eco_sf, band_fanout, bitchat, horizon} sans bornes (avec `--with-beacons` : x {avec `--beacon-count` (defaut 6)/sans bornes}) avec le meme seed pour chaque run
(comparabilite equitable) et affiche un tableau comparatif
(taux de livraison, latence, sauts, overhead, energie, drops).

`--algorithms tide fresh_spray ...` ne lance qu'un sous-ensemble de la
matrice (defaut : tous les algos).

`--seeds 1 2 3 4 5` (alias `--seed`) repete la matrice sur plusieurs seeds :
tous les algos tournent sur les memes seeds (runs apparies), le CSV a une
ligne par run (colonne `seed`) et un `<...>_comparaison_resume.csv` donne,
par algo x bornes, la moyenne et la demi-largeur de l'IC 95 % (Student) de
chaque metrique (`<metrique>_ci95`). Une seule seed ne dit rien de la
variance : viser au moins 5 seeds avant de classer des algos.

`--size small medium large` lance une comparaison complete par taille,
l'une apres l'autre (meme matrice, memes seeds), chacune avec son archive
`<date>_<heure>_comparaison_<taille>.csv` (+ `_resume.csv`, `.json`) ;
`--csv out.csv` devient `out_<taille>.csv` avec plusieurs tailles. Toutes
les configurations sont verifiees avant le premier run : une option
invalide n'archive rien.

`--workers N` (defaut 2) lance N simulations en parallele (un processus
chacune) ; une ligne de statut affiche l'avancement de chaque run en
direct. Chaque comparaison est archivee dans `archives/`
(`--archive-dir` pour changer) : `<date>_<heure>_comparaison.csv`
(`_comparaison_<taille>.csv` avec `--size`) + `.json`
du meme nom (arguments CLI et `SimulationConfig` complete, dans sa
variante avec bornes). Chaque ligne du CSV est ecrite des que son run se
termine, donc un run interrompu garde les resultats deja obtenus.
`--csv CHEMIN` ecrit en plus une copie du CSV.

## Balayer les variantes de band_fanout

    python scripts/sweep_band_fanout.py --seeds 1 2 3 --duration 3600 \
        --num-festivaliers 500 --beacon-count 6 --workers 12 \
        --mobility poi --reply-probability 0.5 [--variant "fanout=2,max_hops=4" ...]

Compare plusieurs configurations de `BandFanoutRouting` (avec
`--beacon-count` bornes) sur plusieurs graines, dans un seul pool de processus, puis
affiche la moyenne par variante (livraison, latence moyenne et p95,
overhead, paquets perdus, energie du mesh).

- `--variant "cle=val,cle=val"` : une variante, option repetable ;
  `--variant ""` = les defauts. Cles : `fanout` (entier), `max_hops`
  (entier), `band_low` et `band_high` (flottants, fractions de la portee),
  `purge_delivered` (`0` ou `1`), `met_dst_window_s` (secondes, ou `none`
  pour desactiver les relais "a croise le destinataire"). Une cle inconnue ou une valeur invalide
  arrete le script avant de lancer quoi que ce soit.
- Sans `--variant`, le script teste 8 variantes : les defauts,
  `purge_delivered=0`, `met_dst_window_s=none`, `band_low=0,band_high=1` (pas de bande), `fanout=2`,
  `fanout=4`, `max_hops=3` et `max_hops=5`.
- `--seeds` (defaut `1 2 3`), `--duration` (defaut 3600), `--num-festivaliers`
  (defaut 200), `--beacon-count` (defaut 6), `--mobility`
  (`random_waypoint` par defaut ou `poi`), `--reply-probability` (defaut 0),
  `--workers` (defaut 2), `--archive-dir` (defaut `archives`), plus les
  options communes (voir "Tout regler avec `--set`"). Pas d'option `--size` ici.
- Archive : `<date>_<heure>_sweep_band_fanout.csv` (une ligne par variante et
  par graine, ecrite des que le run se termine, avec `wall_s`) + `.json` du
  meme nom ; les chaines de variantes ne sont que dans les arguments CLI du
  `.json`.

## Balayer les jetons de `fresh_spray`

    python scripts/sweep_fresh_spray_tokens.py --tokens 4 8 16 32 --seeds 1 2 3 \
        --duration 10800 --num-festivaliers 5000 --beacon-count 6 --workers 12 \
        --mobility poi --reply-probability 0.5

Lance `fresh_spray` pour chaque valeur de `initial_tokens` (`--tokens`,
defaut `4 8 16 32`) et chaque graine (`--seeds`, defaut `1 2 3`), puis
affiche la moyenne par valeur de jetons (livraison, latence moyenne et
p95, surcharge, energie). Memes options que `compare_algorithms.py` pour
le scenario (`--duration` defaut 3600, `--num-festivaliers` defaut 200,
`--beacon-count` defaut 6, `--mobility`, `--size`, `--reply-probability`,
`--workers`, `--archive-dir`) et les memes options communes (voir "Tout
regler avec `--set`"). Archive :
`<date>_<heure>_sweep_fresh_spray_tokens.csv` + `.json` ; la liste des
jetons n'est que dans les arguments CLI du `.json`. Resultats a 5 000
festivaliers : `docs/algorithmes/fresh_spray.md`.

## Trafic

**Debit.** Chaque festivalier tire une fois pour toutes, au debut de la
simulation, son propre debit de messages dans
`TrafficConfig.messages_per_hour_range` (defaut `(0.0, 4.0)` messages/heure,
2 en moyenne ; un debit de 0 = n'envoie jamais), puis envoie selon un
processus de Poisson a ce debit. La charge totale du reseau suit donc
naturellement `num_festivaliers`, sans reglage a faire par scenario.
Chaque message fait 1 000 a 3 800 octets sur le fil (de « ok » a un texte
de 200 caracteres dans le format actuel de l'app, `docs/radio/mesures.md`), vit 1 800 s (`message_ttl_s`) et
au plus 8 sauts de relais (`message_ttl_hops`).

**Destinataire : un ami.** On n'ecrit qu'a ses amis
(`TrafficConfig.friends_only`, defaut `True`). Le graphe d'amis (les QR
codes echanges) est tire une fois par `social.assign_friend_groups`
selon `SimulationConfig.social` :
- 20 % des festivaliers n'ont aucun ami dans l'appli
  (`no_friend_fraction`) et **n'envoient rien** ;
- les autres sont repartis en groupes disjoints de 2 a 8 personnes
  (`group_size_range`), ou tout le monde est ami avec tout le monde ;
- chaque membre d'un groupe a aussi 0 a 2 **amis venus a part**, tires
  dans d'autres groupes (`outside_friends_range`, `social.add_outside_friends`,
  RNG a part `f"{seed}-outside-friends"`) : ils ne se deplacent pas avec
  lui, et ce sont souvent les messages les plus durs a livrer.
  `--no-outside-friends` (`main.py`, `compare_algorithms.py`) les retire ;
- a chaque envoi, le destinataire est un ami actif tire au hasard parmi
  ceux a plus de 15 m (`skip_friends_within_m` : on n'ecrit pas a un ami
  qu'on voit) ; envoi annule si aucun ne reste.

Le meme graphe sert a `bubble_f`. Avec `--mobility group` (defaut de
`--size`), les groupes (sans les amis venus a part) se deplacent
ensemble : les messages vont aux amis venus a part ou naissent des
separations, et bien moins de messages sont crees qu'avec `poi` (voir
`docs/mobilite/group.md`). Avec `random_waypoint` et `poi`, la
mobilite ignore le graphe. `friends_only=False` revient a un
destinataire tire parmi tous les festivaliers actifs.

**Messages de perdu** (`--mobility group` seulement, en plus du rythme
fixe) : pendant un rendez-vous rate, de l'heure prevue jusqu'au retour
dans le groupe (et pour un ami arrive apres son groupe), le perdu ecrit a
un membre du groupe et le meneur ecrit au perdu, chacun a
`TrafficConfig.lost_messages_per_hour` (6/h, estime : « t'es ou ? »),
toujours a plus de 15 m. RNG a part (`f"{seed}-lost"`), qui n'existe que
si le rythme est > 0. Ce sont des messages spontanes, comptes dans le
taux de livraison. `--no-lost-messages` les retire.

**Reponses** (`--reply-probability P`, defaut 0) : un message livre a un
festivalier recoit une reponse avec la probabilite P, envoyee 20 a 180 s
plus tard (`reply_delay_range_s`) si les deux sont encore presents. Une
reponse peut elle-meme recevoir une reponse : on obtient des
conversations. C'est ce qui donne aux algos geographiques (`tide_g`,
`tide_g2`, `geo_spray_focus`) une position recente du destinataire (voir
"GPS" ci-dessous).

**Relances** (`--followup-probability P`, defaut 0) : apres chaque message
spontane (pas apres une reponse), l'emetteur reecrit au meme destinataire
avec la probabilite P, 10 a 120 s plus tard (`followup_delay_range_s`),
et recommence tant que le tirage reussit (chaine geometrique) et que les
deux sont presents.

Reponses et relances sont des messages comme les autres : elles comptent
dans les messages crees et dans le taux de livraison. Leurs tirages
aleatoires n'existent que si P > 0, donc un run sans elles est identique
a ce qu'il etait avant leur ajout.

## GPS

Fourni par le moteur, donc sans effet sur les algos qui ne s'en servent
pas (`GpsConfig`, `SimulationConfig.gps`) :
- **Bruit** : une lecture GPS d'un telephone vaut sa vraie position plus
  un bruit gaussien de 5 m d'ecart-type par axe (`noise_std_m`), retire a
  chaque lecture. Les bornes lisent leur position exacte.
- **Echec de fix** (`--gps-fix-failure P`, defaut 0) : une prise de fix
  echoue avec la probabilite P et ne donne aucune position.
- **Position de la source** : a la creation d'un message, la source y
  joint son fix (`message.src_position`, absent si le fix echoue). A la
  livraison, le destinataire memorise cette position, datee de la
  creation du message (la plus recente l'emporte).
- **Indice sur le destinataire** : a la creation, le message porte la
  derniere position connue du destinataire par la source
  (`message.dst_position`), c'est-a-dire celle du dernier message que le
  destinataire lui a fait parvenir. `tide_g2` et `geo_spray_focus` la
  rapportent aussi dans l'ACK. Sans reponses, l'indice est presque
  toujours absent : les algos geographiques retombent alors sur une
  decision sans geographie.

Le moteur ne facture pas le GPS : les algos qui prennent des fixes
paient eux-memes leur courant (`tide_g`, `geo_spray_focus` : un fix toutes
les 30 s facture 30 s a 10 mA, soit un GPS allume en continu).

## Metriques du rapport

`main.py` affiche le rapport, `compare_algorithms.py` en met les champs en
colonnes du CSV :

| Champ | Definition |
|---|---|
| Taux de livraison (`delivery_ratio`) | messages spontanes livres / messages spontanes crees (relances comprises, **reponses exclues** : leur nombre depend de ce que l'algo a deja livre), sur les seuls messages crees pendant `--duration` : le run continue ensuite `--cooldown` secondes (defaut : le TTL, 1800 s ; trafic compris) pour leur laisser le temps d'arriver. Avant `--duration`, `--warmup` secondes (defaut : 2700, la pause la plus longue) de mobilite seule (ni radio, ni trafic, ni energie) evitent de mesurer le depart synchronise de toute la foule ; les tables de rencontre des algos repartent vides a la fin de la chauffe. Toutes les colonnes de messages, transmissions et pertes ne comptent que ces messages ; l'energie, les noeuds a plat et les evictions couvrent tout le run |
| Latence moyenne / p95 (`avg_latency_s`, `p95_latency_s`) | delai entre la creation et la **premiere** livraison, sur les messages spontanes livres seulement |
| Sauts moyens (`avg_hops`) | sauts de la copie livree en premier (messages spontanes) |
| Reponses (`replies_created`, `replies_delivered`, `reply_delivery_ratio`) | messages crees par `--reply-probability` en reaction a une livraison, rapportes a part. Elles consomment quand meme du debit radio : la charge depend donc encore un peu de l'algo |
| Surcharge (`overhead`) | (tentatives de transmission - messages livres) / messages livres, comme dans The ONE : transmissions en plus de la livraison elle-meme, 0 pour une livraison directe sans autre copie. Une retransmission sur un lien qui perd p compte pour 1/(1-p) tentative. Le backhaul n'y est pas |
| Octets par message livre (`overhead_bytes`) | tous les octets emis (donnees retransmissions comprises, resumes, ACK, tables des algorithmes, diffusions de controle) / messages livres : **le cout radio a comparer entre algorithmes**. Detail dans `data_bytes`, `summary_bytes`, `ack_bytes`, `table_bytes`, `control_bytes` ; seuls les octets non lies a un message emis avant la fin de `--duration` sont comptes |
| Transmissions totales | transmissions BLE reussies (relais et livraisons) |
| Energie totale / moyenne par noeud | consommation des telephones seulement (les bornes, sur secteur, sont exclues), mesh **et** telephone lui-meme (`phone_current_ma`), comptee depuis la charge de depart |
| Energie mesh (`total_mesh_energy_consumed_mah`, ligne « dont mesh ») | la meme sans `phone_current_ma` (rester joignable + emission/reception + couts propres aux algos), les 82 mA du telephone etant identiques pour tous |
| Energie de l'algo (`total_algo_energy_consumed_mah`, ligne « dont algo, hors base ») | l'energie mesh sans `background_current_ma` (31 mA pour rester joignable) : ce que l'algorithme depense lui-meme (emission/reception, connexions, GPS, annonces) : **la colonne a comparer entre algorithmes**. La base ecrase souvent l'ecart entre deux algos dans l'energie mesh, pas ici |
| Noeuds a plat | telephones morts de batterie (`battery_depleted`), pas les departs du churn |
| Copies evincees (buffer) | copies retirees d'un buffer plein pour faire de la place ; le message peut survivre ailleurs, ce n'est pas un message perdu |
| Annonces perdues (`packet_loss_count`) | receptions de diffusions de controle perdues (sans connexion, donc sans renvoi) |
| Octets retransmis (`retransmitted_bytes`) | temps d'antenne des renvois sur les connexions (collisions, signal faible) |
| Transmissions / pertes backhaul | copies entre bornes par le reseau filaire, et celles perdues |

## Valeurs par defaut (festival moyen)

Les defauts de `config.py` et du CLI decrivent un festival de taille
moyenne :
- **Site** : 700 m x 500 m (~0,35 km²), **4 000 festivaliers**.
- **Mobilite** : marche en foule a 0,3-1,2 m/s ; a chaque destination,
  70 % de chances de s'arreter 5 a 45 min (un concert, une file au bar).
- **Trafic** : 0 a 4 messages/heure par personne (2 en moyenne).
- **Batterie** : 4 500 mAh, tout le monde charge a 100 % (`--random-charge`
  pour une charge de depart realiste, de 5 a 100 %).
- **Consommation** (mesuree sur deux telephones, banc radio du 12 oct. 2026) :
  31 mA pour rester joignable (mesh actif) + 82 mA pour le telephone lui-meme
  (veille + ecran, part d'ecran estimee), soit ~40 h d'autonomie a pleine charge ;
  emission ~0,42 µJ/bit, reception ~0,11 µJ/bit. Detail et sources :
  `docs/energie/consommation.md`.
- **Churn** (si active) : arrivees etalees sur les 30 premieres minutes,
  presence de 30 min a 3 h.

## Lancer les tests

    pytest

## Realisme du transfert BLE et surcharge reseau

La portee radio (`src/festival_ble_sim/radio.py`) est derivee d'un modele
de **path-loss log-distance** (memes unites qu'un vrai lien BLE : puissance
d'emission en dBm, exposant d'attenuation, sensibilite du recepteur en
dBm) plutot que d'un rayon fixe arbitraire — `RadioParams` dans
`BleConfig.phone_radio` / `beacon_radio`. La portee effective
(`radio.max_range_m`) est le point ou la puissance recue tombe au niveau
de la sensibilite du recepteur : 30 m pour un telephone, mesures sur le
terrain avec 5 personnes devant le telephone (une borne haute pour une
foule de festival), 60 m pour une borne (non mesure). En plein air le banc
a mesure ~50 m et un exposant de 1,8 (`--set
ble.phone_radio.path_loss_exponent=1.8 --phone-tx-power -19.4`). Mesures,
derivations et recettes : `docs/radio/mesures.md`.

**Fading log-normal** (`RadioParams.shadowing_std_db`, 4 dB par defaut) :
la puissance recue n'est pas qu'une fonction deterministe de la distance,
un echantillon gaussien (obstruction par les corps dans la foule) est
ajoute a chaque tick. Un lien peut donc tomber en dessous de la
sensibilite du recepteur (perte garantie, meme a l'interieur du rayon
"moyen") ou au contraire tenir un peu au-dela — `shadowing_std_db=0.0`
retrouve le modele deterministe (equivalent a un cercle fixe).

**Courant de fond** : chaque telephone actif paie a chaque seconde
`EnergyConfig.background_current_ma` (31 mA, mesh joignable, mesure) +
`phone_current_ma` (82 mA, le telephone lui-meme ecran compris ; 0 pour ne
compter que le mesh), qu'il envoie ou non des messages ; s'ajoute aux couts
par emission/reception. C'est plus de 95 % de la consommation d'un run.
Les pourcentages de batterie des algorithmes se lisent par rapport a la
capacite (`battery_capacity_mah`), l'energie consommee par rapport a la
charge de depart. Voir `docs/energie/consommation.md`.

Le moteur reseau (`src/festival_ble_sim/network.py`) modelise, en plus de
la portee radio :
- un **debit limite par radio et par tick** (`BleConfig.transfer_rate_bytes_per_s`,
  31 ko/s, soit les 0,25 Mbit/s mesures de pres entre deux telephones avec
  5 personnes devant l'un d'eux ; 46 a 68 ko/s en plein air,
  `docs/radio/mesures.md`) :
  emissions et receptions d'un noeud partagent ce budget sur tous ses liens ;
  un message qui ne rentre pas dans le budget de l'emetteur ou du recepteur
  reste en buffer et retente au tick suivant (les emetteurs sont traites dans
  un ordre tire au hasard a chaque tick) ;
- des **connexions** : un lien n'existe que si les deux telephones s'entendent
  (portee mutuelle : une borne ne peut pas joindre un telephone qui ne peut
  pas lui repondre), met `connection_setup_s` (12 s, reconnexion mesuree sur le terrain avec
  Nearby) a
  s'etablir, garde sa place tant que la paire reste a portee et se ferme
  apres `connection_idle_timeout_s` (30 s, estime) sans echange ; un
  telephone tient au plus `max_concurrent_links` connexions (defaut 6),
  comptees des deux cotes ;
- un **canal partage** : un voisin qui emet une part u de son temps
  d'antenne tombe sur le canal d'un paquet avec une probabilite ~u / canaux
  (79 canaux du Bluetooth classique pour les donnees, 3 canaux d'annonce BLE
  pour les diffusions de controle), donc un paquet passe avec une probabilite
  exp(-charge entendue / canaux), sans plafond : une foule dense sature. La
  charge est ce que les voisins ont reellement emis au tick precedent ;
- des **pertes** : collisions ci-dessus, marge de signal faible pres du bord
  de portee (`signal_margin_cutoff_db` / `weak_signal_max_probability`,
  10 dB et 0,6, cales sur la baisse du debit mesuree avec la distance) et
  perte residuelle (`packet_loss_base_probability`). Sur une connexion chaque
  paquet est acquitte et renvoye : une perte p coute 1/(1-p) fois le temps
  d'antenne et l'energie (`retransmitted_bytes` du rapport) au lieu de perdre
  le message ; seule une vraie panne radio (fading negatif, cf. ci-dessus)
  ne laisse rien passer ce tick. Une diffusion de controle, sans connexion,
  est perdue ou non (`packet_loss_count`) ;
- un **transport sans connexion** pour les algorithmes qui le declarent
  (`advertising_bearer`, `managed_flood` comme Bluetooth Mesh) : pas de
  connexion a etablir, chaque message part une fois vers tous les voisins
  que l'algo choisit, sur les canaux d'annonce, et chaque reception est
  perdue ou non (pas de renvoi) ;
- des **ACK et metadonnees payes** : a chaque tick, sur chaque connexion
  etablie et avant les donnees, chaque cote envoie son vecteur de resume
  (4 octets par message pas encore annonce sur cette connexion), les ACK
  que l'autre demande (messages qu'il annonce et dont celui-ci sait qu'ils
  sont livres, 210 octets chacun comme un accuse de reception de l'app ;
  222 avec la position pour `tide_g2` et `geo_spray_focus`) et, une fois par connexion, les tables de
  l'algorithme (dates de rencontre, predictibilites...). Tout cela coute du
  temps d'antenne, des retransmissions et de l'energie comme les donnees.
  Le destinataire emet l'ACK a la livraison ; un telephone qui l'apprend
  supprime sa copie, et la source le recoit comme un accuse de reception.
  Aucun algorithme ne voit plus d'ensemble global des messages livres ;
- un **TTL reseau en nombre de sauts** (`TrafficConfig.message_ttl_hops`,
  defaut 8, a la Bluetooth Mesh) en plus du TTL temporel `message_ttl_s` :
  un message qui a deja consomme son budget de sauts n'est plus relaye a
  de nouveaux noeuds mais reste livrable directement a sa destination si
  elle est a portee (meme semantique que la "phase wait" de Spray & Wait) ;
- un **backhaul borne-a-borne pas tout a fait instantane ni fiable**
  (`BeaconConfig.backhaul_latency_s` / `backhaul_loss_probability`) :
  actif des que 2 bornes ou plus sont presentes, hors contraintes de
  portee/debit/perte du lien BLE, mais avec une probabilite d'essai par
  tick (`contact_check_interval_s / backhaul_latency_s`, plafonnee a 1)
  et une perte possible — par defaut proche de l'instantane/fiable
  d'origine, a durcir via la config pour un backbone plus realiste.

Ces effets sont visibles dans le rapport via `Copies evincees (buffer)`,
`Paquets perdus (radio)`, `Transmissions backhaul`,
`Backoffs (contention)` et `Paquets perdus (backhaul)`.

## Churn (arrivees/departs des festivaliers)

Par defaut, tous les noeuds mobiles sont presents et actifs pendant toute
la duree de la simulation. `ChurnConfig` (`SimulationConfig.churn`, ou
`--churn` en CLI) permet de simuler une foule qui arrive et repart en
continu plutot qu'un evenement figé : chaque noeud tire un instant
d'arrivee dans `arrival_window_s` et une duree de presence dans
`session_duration_range_s`, et n'est `is_active` (participe au BLE,
eligible comme source/destination de trafic) qu'entre les deux — le meme
mecanisme deja utilise pour les noeuds a court de batterie. Un noeud non
encore arrive ou deja parti ne bouge plus (`BaseNode.on_site`, que seul le
churn change) et disparait des replays HTML ; un festivalier dont le
telephone est mort continue de marcher (et de mener son groupe), seule sa
radio s'eteint. `SimulationReport.dead_node_count`
ne compte que les morts par batterie (`BaseNode.battery_depleted`), pas
les departs de churn.

## Visualisation / replay

`--replay-html` enregistre les positions (un instantane tous les
`--replay-frame-step` secondes) et les evenements de relais/livraison pendant
le run, puis ecrit `archives/replay/<date>_<algo>.html` (page Canvas + JS,
aucune dependance externe) et `<date>_<algo>.data.js` a cote (les donnees,
une frame / un evenement par ligne). Le `.html` n'a pas de donnees en dur : il
charge le `.data.js` par `<script src>` (un `fetch` de JSON est bloque en
`file://`), donc les deux fichiers doivent rester ensemble. Lecture/pause et
curseur temporel — telephones et bornes en points, liens de relais/livraison
de la frame courante en traits.

Pour rester ouvrable avec un algo qui inonde (epidemic : ~23 millions de
relais pour 4 000 noeuds en 1 h), les positions sont arrondies a 0,1 m et les
relais ne sont gardes que pour `--replay-max-messages` messages (livres en
priorite, repartis sur la duree) ; les autres messages livres gardent leur
seule livraison. Les evenements sont stockes en colonnes pendant le run
(`CompactEventLog`) pour ne pas payer un dict par relais en memoire.

Le panneau "Suivre un message" liste les messages relayes (livres en
premier, plus de sauts d'abord). En choisir un grise le reste et affiche
sa source, son destinataire, les porteurs de copies, chaque relais avec
son numero de saut (chemin livre en vert, backhaul des bornes en
pointille orange) et une chronologie cliquable ; "Suivre depuis la
creation" lance la lecture au bon moment. Les copies purgees ou evincees
ne sont pas enregistrees : un porteur reste affiche jusqu'a la fin. Un message
hors echantillon n'affiche que sa livraison.
Programmatiquement :

    from festival_ble_sim.config import SimulationConfig
    from festival_ble_sim.simulation import run_simulation
    from festival_ble_sim.viz.history import SimulationHistory
    from festival_ble_sim.viz.replay import render_replay_html

    config = SimulationConfig(duration_s=300, num_festivaliers=50)
    history = SimulationHistory(
        area_width_m=config.area.width_m,
        area_height_m=config.area.height_m,
        tick_interval_s=config.mobility.tick_interval_s,
    )
    run_simulation(config, history=history)
    render_replay_html(history, "replay.html")

## Modeles de mobilite disponibles

Principe, diagramme, plans de site, ordres de grandeur, forces et
faiblesses : un fichier par modele dans `docs/mobilite/`.

- `group` (`mobility/group.py`, defaut avec `--size`) — les groupes
  d'amis (sans les amis venus a part) se deplacent ensemble autour d'un
  meneur (le premier membre present) qui suit `poi` ; un membre part
  parfois, seul ou avec la moitie du groupe (30 % des sorties), (bar
  5-30 min, autre scene 30 min-2 h), apres avoir fixe un rendez-vous ou le
  groupe l'attend 15 min, sinon il cherche le groupe de point d'interet en
  point d'interet, comme un ami arrive apres son groupe. Personne n'ecrit
  a un ami qu'il voit (`TrafficConfig.skip_friends_within_m`, 15 m) ;
  perdu et groupe s'ecrivent en plus pendant un rendez-vous rate. Voir
  `docs/mobilite/group.md`.
- `random_waypoint` (`mobility/random_waypoint.py`, defaut) — cible
  uniforme sur toute la zone, puis pause (70 % de chances, 5 a 45 min).
  Voir `docs/mobilite/random_waypoint.md`.
- `poi` (`mobility/poi.py`) — meme alternance marche/pause, mais vers
  des points d'interet ponderes (`MobilityConfig.points_of_interest`,
  liste de `PointOfInterest(x, y, radius_m, weight)`), pour representer
  une foule qui converge vers des scenes/stands. Le CLI (`--mobility poi`)
  l'utilise avec le plan `mobility.poi.default_festival_pois` : grande
  scene (poids 4), bars/restauration (3), deuxieme scene (2),
  entree/toilettes (1) ; `--size` le remplace par une zone dense
  (`presets.crowd_mobility_config`). Pour un autre plan, construis un
  `MobilityConfig(points_of_interest=(...))` et passe-le a
  `SimulationConfig(mobility=...)`. Voir `docs/mobilite/poi.md`.

## Algorithmes de routage disponibles

Forces et faiblesses detaillees : un fichier par algorithme dans `docs/algorithmes/`.
Specification complete (regles exactes, parametres, ecarts avec la reference) :
un fichier par algorithme dans `docs/algorithmes/specs/`.

- `epidemic` (`routing/epidemic.py`) — flooding naif, reference/borne haute
  d'overhead.
- `spray_wait` (`routing/spray_and_wait.py`) — nombre limite de copies
  diffusees puis attente de contact direct avec la destination.
- `prophet` (`routing/prophet.py`) — routage probabiliste par
  predictabilite de rencontre entre noeuds, avec vieillissement dans le
  temps.
- `beacon_priority` (`routing/beacon_priority.py`) — privilegie le forward
  vers une borne des qu'elle est en contact (exploite le backhaul) puis
  arrete de flooder les autres telephones ; degenere en `epidemic` sans
  borne.
- `dasfv` (`routing/dasfv.py`) — DASF-V v2 (Density-Aware Spray-and-Focus
  with Verifiable ACK/purge), reduit au sous-ensemble pertinent pour ce
  simulateur reseau (pas de crypto/GATT/SOS/epoques, voir le commentaire
  d'en-tete du fichier) : budget de copies initial adapte a la densite
  locale, spray puis focus par gradient d'utilite PRoPHET, relais a 2 sauts
  et heuristique de mule approximes a partir des contacts observes par
  l'instance partagee, politique batterie (refus des pairs a batterie
  critique, evacuation acceleree du porteur a batterie faible), et purge
  des copies par l'ACK du moteur (voir "ACK et metadonnees").
- `gossip_a` (`routing/gossip_a.py`) — GOSSIP-A, gossip probabiliste
  adaptatif a la densite avec anti-entropie, reduit lui aussi au
  sous-ensemble reseau (pas de crypto/etiquettes/PoW/SOS) : probabilite de
  retransmission `p = clamp(C / densite, P_MIN, 1)` tiree une fois par
  (message, pair) et par session, inondation des `K_FLOOD` premiers sauts,
  borne `H_MAX`, faux positifs du Bloom SUMMARY, suppression par compteur
  (message deja vu chez `K_SUP` voisins), jetons de purge propages de
  proche en proche (son propre mecanisme, facture comme un Bloom
  PURGE_SYNC de 2 000 octets par connexion : son Bloom de 128 o au
  format de l'app, `docs/radio/mesures.md`), budgets par session et eviction du buffer « plus
  repliques d'abord » (hook `RoutingAlgorithm.choose_eviction`). Les
  interrupteurs `adaptive`, `suppression` et `replicated_first_eviction`
  servent aux ablations.
- `bubble_f` (`routing/bubble_f.py`) — BUBBLE-F, routage social inspire de
  BUBBLE Rap : communautes amorcees par le graphe d'amis (QR) partage de la
  simulation (`SimulationConfig.social` : groupes de 2 a 8, 20 % sans ami
  par defaut ; le meme graphe que celui du trafic),
  enrichies par SIMPLE (familiers apres 20 min de contact cumule, ajout par
  recouvrement, fusion), rangs global/local C-Window (4 fenetres de 30 min),
  budget de 8 jetons en division binaire : entrer dans la bulle du
  destinataire, sinon monter en rang global, puis en rang local a
  l'interieur. Relais a 2 sauts, replication anti-blocage apres 30 min sans
  progres, admission restreinte des buffers pleins a 80 %, epoques
  optionnelles (`epoch_s`). Les Bloom, `rankCap`, SOS et RSSI ne sont pas
  modelises (instance partagee = vues exactes, pas d'attaquant). Avec
  `random_waypoint` ou `poi`, les amis ne se deplacent pas ensemble et la
  bulle apporte peu ; elle prend son sens avec `--mobility group`.
- `managed_flood` (`routing/managed_flood.py`) — inondation geree du
  Bluetooth Mesh (couche reseau), sans stockage-transport : un noeud ne
  relaie un PDU que pendant `relay_window_s` apres l'avoir recu, puis
  l'oublie. Boucles et tempetes bornees par le TTL (`ttl`, en sauts), un
  cache de messages par noeud de taille fixe (`cache_size`, FIFO, cle
  `(msg_id, SEQ)`) qui rejette tout PDU deja vu, et la fenetre de relais.
  Mode acquitte (`acknowledged=True`, defaut) : la destination emet un
  ACK propage par inondation geree (memes regles TTL/fenetre) qui purge
  les copies ; la source oublie elle aussi le PDU apres sa fenetre (pas
  de stockage-transport cote source) et, sans ACK apres `ack_timeout_s`,
  le reemet avec un nouveau SEQ, au plus `max_source_retransmissions`
  fois. Chaque saut d'ACK coute l'energie tx/rx de `ack_size_bytes`
  (defaut 16 o : un ACK inonde part en diffusion, en binaire, pas au format
  JSON de l'app) mais pas de bande passante (le budget de lien du moteur ne
  le voit pas). Pense pour une topologie connexe : en festival clairseme,
  la livraison chute par rapport aux algos DTN, c'est attendu.
- `bitchat` (`routing/bitchat.py`) — messages prives de bitchat (code iOS
  `permissionlesstech/bitchat`, constantes par defaut), sous-classe de
  `managed_flood` : inondation dirigee TTL 7 avec dedup 1000 ids / 300 s,
  envoi au seul destinataire s'il est voisin, spool 60 s chez un relais
  isole ; la source n'inonde que si la destination est joignable (annonce
  sur 7 sauts, 5 en zone dense, retenue 60 s) et reemet a chaque retour,
  8 envois max ; sinon elle confie le message a 3 couriers max (amis
  d'abord, spray-and-wait 4 copies) qui livrent au contact ou relancent une
  inondation quand ils entendent la destination. Spec :
  `docs/algorithmes/specs/BITCHAT.md`.
- `tide` (`routing/tide.py`) — TIDE (Tokens, Islands, Density, Energy),
  candidat NICE : jetons initiaux `L0 = clamp(round(16 sqrt(10/rho)), 2, 16)`
  partages au prorata de l'utilite `U = e * [w P + (1-w) exp(-dt/tau)]`,
  livraison directe dans les ilots (tout voisin qui voit la destination
  recoit une copie), relais elus toutes les 5 min avec
  `p = min(1, rho_cible/rho * e/e_moy)` (membres et feuilles < 15 % ne
  portent pas les messages des autres, repli relais apres 30 s sans relais
  visible), K synchros par minute, copie fantome et reinjection par la
  source a 3/6/20 min, purge par ACK et eviction (acquittes, expires, en
  retard, copies a 1 jeton de faible utilite, jamais les messages propres).
  Non modelises : crypto, ID ephemeres, digests, cycle de scan/annonce,
  quota par emetteur, reputation, ordre de transmission. La transitivite
  PRoPHET est desactivee par defaut (`enable_transitivity`) car en O(N^2)
  a 4000 noeuds. Interrupteurs d'ablation : `islands`, `weighted_tokens`,
  `election`, `reinjection`, `energy_factor`.
- `tide_g` (`routing/tide_g.py`) — TIDE-G, TIDE guide par la derniere
  position connue du destinataire (`message.dst_position`, fournie par le
  destinataire lui-meme dans son dernier message a la source). Indice
  utilisable s'il a moins de 15 min, arrondi a une case de 25 m, disque
  d'incertitude `r = 30 + 0,3 h` m. Les relais elus et les porteurs d'un
  message a indice prennent un fix GPS toutes les 30 s (10 mA factures).
  Change trois regles de TIDE : partage des jetons sur
  `S = max(U, e kappa g)`, focus geographique (copie unique passee a un
  voisin au moins 15 m plus pres de l'indice), recherche locale (3 jetons
  « zone » une fois dans le disque) ; la source rafraichit l'indice si elle
  a recu une position plus recente. Sans indice, identique a TIDE.
  `hint_stats` donne la couverture d'indice. A lancer avec `--mobility poi
  --reply-probability 0.5`. Details dans `docs/algorithmes/tide_g.md`,
  spec complete dans `docs/algorithmes/specs/TIDE-G.md`. Interrupteurs d'ablation :
  `geo_focus`, `geo_tokens`, `zone_search`, `refresh_hint`, `gps_for_relays`.
- `tide_g2` (`routing/tide_g.py`, preset `TIDE_G2_KWARGS`) — TIDE-G + trois
  ajouts : l'ACK rapporte a la source la position du destinataire (apres
  un trajet retour aussi long que l'aller), l'indice est abandonne 180 s
  apres la creation du message (retour a TIDE pur), et les fixes ponctuels
  a l'envoi et a l'ACK sont factures (5 s de GPS sauf fix periodique
  frais). Deux autres ajouts restent des ablations hors preset :
  `hint_scaled_tokens` (premier spray reduit) et `relay_hint_merge` (fusion
  d'indices dans le buffer d'un relais). `hint_stats` ajoute
  `hinted_by_ack`, `delivered_after_giveup`, `message_fixes`... Tous les
  ajouts sont desactives par defaut : `tide_g` est inchange. A lancer avec
  `--mobility poi --reply-probability 0.5 --followup-probability 0.5`.
  Spec dans `docs/algorithmes/specs/TIDE-G2.md`.
- `fresh_spray` (`routing/fresh_spray.py`) — Spray binaire (`initial_tokens`,
  defaut 16) + replique vers tout voisin ayant croise la destination depuis
  moins de `met_dst_window_s` (1200 s) + passage de la derniere copie au
  voisin qui a vu la destination plus recemment (FRESH) + une seule replique
  vers le reseau de bornes + purge par l'ACK du moteur. Vise a la
  fois livraison, latence et energie ; details dans
  `docs/algorithmes/fresh_spray.md`.
- `horizon` (`routing/horizon.py`) — `fresh_spray` + champ de distances
  en sauts : toutes les 5 s, a sa propre phase, chaque noeud diffuse son
  vecteur de distances (destinations a `horizon_hops` = 5 sauts ou moins),
  reconstruit a partir du dernier vecteur entendu de chaque voisin depuis
  moins de 15 s, avec split horizon (chaque entree porte le prochain saut)
  et plafonnes a 1650 octets ; les vecteurs passent par la radio du moteur
  comme des messages (temps d'antenne, charge du canal, pertes, energie), et ceux
  d'un emetteur injoignable (borne de plus grande portee) sont ignores. Une copie dont le
  porteur a un voisin plus proche du destinataire lui est passee (tirage,
  un saut par tick) si le TTL de sauts restant suffit ; hors tirage, une
  copie a `hops >= ttl_hops - horizon_hops` ne se replique plus (reserve
  pour le tirage) ; `select_links` donne les liaisons aux prochains sauts
  d'abord. Spec dans `docs/algorithmes/specs/HORIZON.md`.
- `geo_spray_focus` (`routing/geo_spray_focus.py`) — GSF, Spray-and-Focus
  autonome guide par la derniere position connue du destinataire : budget
  de 2 a 12 copies selon l'aire d'incertitude de l'indice, spray refuse a
  un voisin nettement plus loin de l'indice, derniere copie passee a un
  voisin au moins 15 m plus pres (sinon a qui a croise le destinataire le
  plus recemment), regle des ilots. La source escalade un message non
  livre : 12 jetons sans geographie a 60 s, puis inondation a 180 s
  (bornee par le TTL de 8 sauts). Purge par l'ACK du moteur, qui renvoie
  la position du destinataire a la source. `stats` donne la
  repartition des transmissions par raison. Le gain mesure vient de
  l'inondation tardive, pas de la geographie : variante sans GPS
  `GeoSprayFocusRouting(hint_max_age_s=1e-9, gps_policy="carriers",
  ack_hint=False)`. Spec dans `docs/algorithmes/specs/GSF.md`.
- `eco_sf` (`routing/eco_sf.py`) — ECO-SF, Spray-and-Focus sans GPS econome
  en reveils radio. Modelise : beacons a cadence Trickle (Imin 2 s, Imax
  30/60/120 s selon la batterie, suppression k = 1) qui conditionnent la
  decouverte (pas de connexion sans beacon entendu dans un sens), utilite
  PRoPHET allegee (vieillissement par minute, table de 64 entrees,
  transitivite sur les 32 meilleures, echangee seulement en connexion),
  budget de 2 a 16 copies selon les voisins entendus sur 60 s, partage
  pondere par l'utilite (25-75 %), focus avec hysteresis `delta`, connexion
  seulement si le voisin a une utilite > `dest_bloom_threshold` (0.05)
  pour un message qu'il n'a pas, cooldown de 20 s par paire, plus aucun
  relais apres 10 min (livraison directe seulement), batterie < 20 % :
  refuse les relais, < 10 % : muet sauf message propre, eviction par
  priorite sans toucher aux messages propres. Les beacons passent par la
  radio (diffusions de 64 octets, estime), les ACK par le moteur. Omis :
  Bloom filters (lus comme des ensembles exacts, sans faux positifs),
  signature des ACK, ordre de transfert par priorite, EWMA de la densite,
  plafond de resets anti-spam. `stats` compte beacons, resets Trickle, connexions, spray et focus. Spec et
  resultats dans `docs/algorithmes/specs/ECO-SF.md`.
- `band_fanout` (`routing/band_fanout.py`) — relais a eventail borne :
  chaque copie peut etre relayee `fanout` fois (3 par defaut), la copie
  relayee repart avec un budget neuf, puis il ne reste que la livraison
  directe. Les relais sont tires au hasard (graine `seed`) parmi les
  voisins dont la distance GPS vaut 40 a 60 % de la portee (`band`, soit
  12 a 18 m, environ 6 a 11 dB de marge de liaison) : assez loin pour
  etendre la diffusion, pas au bord de portee ou le shadowing fait perdre
  des paquets. Si la bande compte moins de `fanout` voisins, complete avec
  ceux qui en sont les plus proches. Le classement porte sur tous les
  voisins ; le plafond `max_concurrent_links` (6) reste applique, mais
  l'algo choisit lui-meme ses liaisons via le hook `select_links` (relais
  retenus d'abord, puis les plus proches), sinon la bande serait hors
  d'atteinte en foule dense. Plafond de `max_hops` (4) sauts en plus du TTL du moteur. Les
  copies sont purgees par l'ACK du moteur (`purge_delivered=True`), propage
  et facture sur les connexions. Sans purge, l'arbre de copies (jusqu'a 121 porteurs)
  continue d'etre transmis apres la livraison. Les voisins qui ont ete a
  portee du destinataire dans les `met_dst_window_s` dernieres secondes
  (1200 par defaut, `None` desactive) recoivent la copie sans entamer le
  budget du porteur ; la copie qu'ils recoivent n'est ensuite relayee qu'a
  d'autres voisins de ce type (ou livree). Pas d'eviction dediee.
  `scripts/sweep_band_fanout.py` (options : voir "Balayer les variantes de
  band_fanout") compare des variantes (`--variant
  "fanout=2,max_hops=4"`, cles : `fanout`, `max_hops`, `band_low`,
  `band_high`, `purge_delivered`, `met_dst_window_s`) sur plusieurs graines ;
  sans `--variant`, il teste les defauts, l'absence de purge, la bande
  0-100 %, `fanout` 2 et 4, `max_hops` 3 et 5. Resultats et diagramme dans
  `docs/algorithmes/band_fanout.md`, spec dans
  `docs/algorithmes/specs/BAND-FANOUT.md`.

## Ajouter un nouvel algorithme de routage

1. Cree un fichier dans `src/festival_ble_sim/routing/`, par exemple
   `routing/mon_algo.py`, et sous-classe `RoutingAlgorithm`
   (`routing/base.py`) :

       from __future__ import annotations
       from typing import TYPE_CHECKING
       from ..models import Message
       from .base import RoutingAlgorithm, RoutingDecision

       if TYPE_CHECKING:
           from ..nodes import BaseNode

       class MonAlgoRouting(RoutingAlgorithm):
           def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
               if contact.has_message(message.msg_id):
                   return RoutingDecision.IGNORE
               return RoutingDecision.FORWARD  # ta logique ici

   Seule `decide()` est obligatoire. Des hooks optionnels (no-op par
   defaut) sont disponibles :
   - `on_simulation_start(nodes)` — appele une fois avant le debut du run,
     avec tous les noeuds (ex. `routing/bubble_f.py` y lit le graphe
     d'amis via `node.friends`).
   - `on_tick(now, neighbors_by_node)` — appele a chaque tick avec toutes
     les paires a portee, meme sans message a envoyer : `decide()` seul ne
     voit que les contacts ou le porteur a un message, ce qui sous-estime
     l'historique de contacts.
   - `on_delivered(message, holder)` — appele quand `message` vient
     d'atteindre sa destination.
   - `on_forward(message, holder, contact, forwarded_copy)` — appele juste
     apres qu'une copie independante (`forwarded_copy`) a ete creee et
     stockee chez `contact`. Utile pour un etat par-copie asymetrique
     (ex. `routing/spray_and_wait.py` y repartit les copies restantes
     entre holder et contact).
   - `choose_eviction(node, now)` — appele quand une copie arrive dans un
     buffer plein : renvoie l'id du message a evincer, ou `None` pour
     garder l'eviction FIFO par defaut (ex. `routing/gossip_a.py`).

   Points a respecter (voir `CLAUDE.md`) :
   - ne jamais importer `BaseNode`/`BeaconNode` en dehors de
     `TYPE_CHECKING` (le package `routing/` doit rester duck-type) — pour
     distinguer une borne d'un telephone, utilise `getattr(contact, "is_beacon", False)`
     comme le fait `routing/beacon_priority.py`.
   - un etat par run (ex. table de predictabilite PRoPHET) peut vivre
     directement sur l'instance de l'algo (`self._mon_etat = {}` dans
     `__init__`), car une seule instance partagee sert tout le run
     (voir `simulation.py`).
   - un etat par message (ex. `copies_left` de Spray & Wait) se stocke dans
     `message.routing_state[...]` (dict libre reserve a cet usage).

2. Rends-le selectionnable depuis le CLI et le script de comparaison en
   l'ajoutant aux deux tables de correspondance :
   - `main.py` → `ROUTING_FACTORIES["mon_algo"] = lambda args: MonAlgoRouting()`
     (les `choices` de `--routing` en sont derives automatiquement).
   - `scripts/compare_algorithms.py` → `ALGORITHMS["mon_algo"] = MonAlgoRouting`.

   Ou utilise-le directement sans passer par le CLI :

       from festival_ble_sim.config import SimulationConfig
       from festival_ble_sim.simulation import run_simulation
       from festival_ble_sim.routing.mon_algo import MonAlgoRouting

       report = run_simulation(SimulationConfig(), routing_algorithm=MonAlgoRouting())

3. Ajoute des tests dans `tests/test_routing_mon_algo.py` (voir
   `tests/test_routing_beacon_priority.py` pour un exemple minimal avec de
   faux noeuds, et `tests/test_routing_spray_and_wait.py` pour un exemple
   qui verifie aussi l'integration reelle via `process_node_contacts`).

## Architecture

Voir `docs/superpowers/specs/2026-09-14-festival-ble-sim-design.md`
pour le design complet. Points d'injection pour tes propres
algorithmes :
- `src/festival_ble_sim/routing/` — nouveaux algorithmes de routage
  (implemente `RoutingAlgorithm`, avec les hooks optionnels
  `on_simulation_start`, `on_tick`, `on_delivered`, `on_forward` et
  `choose_eviction`).
- `src/festival_ble_sim/mobility/` — nouveaux modeles de mobilite
  (implemente `MobilityModel`).
- `src/festival_ble_sim/beacons.py` — placement strategique des bornes.

Exemple d'injection d'un algorithme ou d'un modèle de mobilité personnalisé :

    from festival_ble_sim.config import SimulationConfig
    from festival_ble_sim.simulation import run_simulation

    report = run_simulation(
        SimulationConfig(),
        routing_algorithm=MyRoutingAlgorithm(),
        mobility_factory=lambda rng: MyMobilityModel(rng),
    )
