# Festival BLE Mesh Simulator

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

Options disponibles :
- `--routing` : `epidemic` (defaut), `spray_wait`, `prophet`,
  `beacon_priority`, `dasfv`, `gossip_a`, `bubble_f` ou `managed_flood` (un seul choix a la fois, pas de `|`)
- `--mobility` : `random_waypoint` (defaut) ou `poi` (les festivaliers
  se repartissent entre scenes, bars et entree, voir plus bas)
- `--beacons N` : nombre de bornes (0 = desactivees, defaut)
- `--beacon-placement` : `grid` (defaut) ou `manual`
- `--duration`, `--num-festivaliers`, `--seed`
- `--archive-dir DOSSIER` : dossier d'archive (defaut `archives`)
- `--output CHEMIN` : copie optionnelle du rapport, en plus de l'archive
- `--spray-initial-copies` : propre a `spray_wait` (defaut 8)
- `--replay-html CHEMIN` : ecrit un replay HTML autonome de la simulation
  (voir "Visualisation / replay" plus bas)
- `--churn`, `--churn-arrival-window-s LO HI`, `--churn-session-duration-s LO HI` :
  arrivees/departs echelonnes des festivaliers (voir "Churn" plus bas)

## Comparer les algorithmes

    python scripts/compare_algorithms.py --seed 42 --duration 3600 \
        --num-festivaliers 200 --beacon-count 6 --workers 2 [--csv comparaison.csv]

Lance automatiquement la matrice {epidemic, spray_wait, prophet,
beacon_priority, dasfv, gossip_a, bubble_f, managed_flood} x {avec/sans bornes} avec le meme seed pour chaque run
(comparabilite equitable) et affiche un tableau comparatif
(taux de livraison, latence, sauts, overhead, energie, drops).

`--workers N` (defaut 2) lance N simulations en parallele (un processus
chacune) ; une ligne de statut affiche l'avancement de chaque run en
direct. Chaque comparaison est archivee dans `archives/`
(`--archive-dir` pour changer) : `<date>_<heure>_comparaison.csv` + `.json`
du meme nom (arguments CLI et `SimulationConfig` complete, dans sa
variante avec bornes). Chaque ligne du CSV est ecrite des que son run se
termine, donc un run interrompu garde les resultats deja obtenus.
`--csv CHEMIN` ecrit en plus une copie du CSV.

## Trafic

Chaque festivalier tire une fois pour toutes, au debut de la simulation,
son propre debit de messages dans `TrafficConfig.messages_per_hour_range`
(defaut `(0.0, 2.0)` messages/heure ; un debit de 0 = n'envoie jamais),
puis envoie selon un processus de Poisson a ce debit vers un autre
festivalier actif tire au hasard. La charge totale du reseau suit donc
naturellement `num_festivaliers`, sans reglage a faire par scenario.

## Valeurs par defaut (festival moyen)

Les defauts de `config.py` et du CLI decrivent un festival de taille
moyenne :
- **Site** : 700 m x 500 m (~0,35 km²), **4 000 festivaliers**.
- **Mobilite** : marche en foule a 0,3-1,2 m/s ; a chaque destination,
  70 % de chances de s'arreter 5 a 45 min (un concert, une file au bar).
- **Trafic** : 0 a 4 messages/heure par personne (2 en moyenne).
- **Batterie** : 3 000 mAh au depart (telephone ~4 500 mAh charge aux
  deux tiers).
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
de la sensibilite du recepteur.

**Fading log-normal** (`RadioParams.shadowing_std_db`, 4 dB par defaut) :
la puissance recue n'est pas qu'une fonction deterministe de la distance,
un echantillon gaussien (obstruction par les corps dans la foule) est
ajoute a chaque tick. Un lien peut donc tomber en dessous de la
sensibilite du recepteur (perte garantie, meme a l'interieur du rayon
"moyen") ou au contraire tenir un peu au-dela — `shadowing_std_db=0.0`
retrouve le modele deterministe (equivalent a un cercle fixe).

Le moteur reseau (`src/festival_ble_sim/network.py`) modelise, en plus de
la portee radio :
- un **debit limite par lien et par tick** (`BleConfig.transfer_rate_bytes_per_s`) :
  un message qui ne rentre pas dans le budget reste en buffer et retente
  au tick suivant ;
- une **limite de connexions BLE simultanees** (`max_concurrent_links`,
  defaut 6, realiste pour un smartphone) — au-dela, les contacts les plus
  proches sont prioritaires ;
- un **backoff a la CSMA** (`relay_backoff_coefficient` /
  `relay_backoff_max_probability`) : avant d'emettre, un noeud estime
  combien d'autres noeuds a sa portee ont aussi quelque chose a envoyer ce
  tick, et renonce (retente au tick suivant, sans energie ni perte
  comptabilisee) avec une probabilite qui croit avec ce nombre — c'est ce
  qui evite que tous les noeuds emettent en meme temps ;
- une **collision "hidden-terminal"** (`collision_loss_coefficient` /
  `collision_loss_max_probability`) : meme apres backoff, un recepteur
  entoure de plusieurs emetteurs qui ne s'entendent pas entre eux peut
  perdre le paquet — un cout distinct de la congestion normale ;
- une **perte de paquets probabiliste**, combinant plusieurs composantes :
  congestion (`packet_loss_congestion_coefficient`), marge de signal
  faible pres du bord de portee (`signal_margin_cutoff_db` /
  `weak_signal_max_probability`) et collision ci-dessus, plafonnees par
  `packet_loss_max_probability` — sauf une vraie panne radio (fading
  negatif, cf. ci-dessus), qui est une perte garantie et ignore ce plafond ;
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

Ces effets sont visibles dans le rapport via `Messages perdus (buffer)`,
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
encore arrive ou deja parti ne bouge plus (`_mobile_process` le laisse en
pause) et disparait des replays HTML. `SimulationReport.dead_node_count`
ne compte que les morts par batterie (`BaseNode.battery_depleted`), pas
les departs de churn.

## Visualisation / replay

`--replay-html CHEMIN` enregistre les positions (un instantane par tick
de mobilite) et les evenements de relais/livraison pendant le run, puis
ecrit un fichier HTML autonome (Canvas + JS, aucune dependance externe)
avec lecture/pause et curseur temporel — telephones et bornes en points,
liens de relais/livraison du tick courant en traits. Cout memoire
proportionnel a `duration x num_festivaliers` : a reserver aux scenarios
modestes (quelques dizaines/centaines de noeuds), pas au run par defaut
a 4 000 festivaliers. Programmatiquement :

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

- `random_waypoint` (`mobility/random_waypoint.py`, defaut) — cible
  uniforme sur toute la zone.
- `poi` (`mobility/poi.py`) — les noeuds alternent pause/deplacement vers
  des points d'interet ponderes (`MobilityConfig.points_of_interest`,
  liste de `PointOfInterest(x, y, radius_m, weight)`), pour representer
  une foule qui converge vers des scenes/stands plutot qu'un mouvement
  brownien uniforme. Le CLI (`--mobility poi`) l'utilise avec un plan de
  festival par defaut (`main._default_festival_pois`) : grande scene
  (poids 4), bars/restauration (3), deuxieme scene (2), entree/toilettes
  (1) ; pour plusieurs points d'interet ponderes, construis directement
  un `MobilityConfig(points_of_interest=(...))` et passe-le a
  `SimulationConfig(mobility=...)`.

## Algorithmes de routage disponibles

Forces et faiblesses detaillees : un fichier par algorithme dans `docs/algorithmes/`.

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
  reseau-large des copies une fois le message livre.
- `gossip_a` (`routing/gossip_a.py`) — GOSSIP-A, gossip probabiliste
  adaptatif a la densite avec anti-entropie, reduit lui aussi au
  sous-ensemble reseau (pas de crypto/etiquettes/PoW/SOS) : probabilite de
  retransmission `p = clamp(C / densite, P_MIN, 1)` tiree une fois par
  (message, pair) et par session, inondation des `K_FLOOD` premiers sauts,
  borne `H_MAX`, faux positifs du Bloom SUMMARY, suppression par compteur
  (message deja vu chez `K_SUP` voisins), jetons de purge propages de
  proche en proche, budgets par session et eviction du buffer « plus
  repliques d'abord » (hook `RoutingAlgorithm.choose_eviction`). Les
  interrupteurs `adaptive`, `suppression` et `replicated_first_eviction`
  servent aux ablations.
- `bubble_f` (`routing/bubble_f.py`) — BUBBLE-F, routage social inspire de
  BUBBLE Rap : communautes amorcees par un graphe d'amis (QR) genere au
  lancement (groupes de 2 a 8, 20 % d'utilisateurs sans ami par defaut),
  enrichies par SIMPLE (familiers apres 20 min de contact cumule, ajout par
  recouvrement, fusion), rangs global/local C-Window (4 fenetres de 30 min),
  budget de 8 jetons en division binaire : entrer dans la bulle du
  destinataire, sinon monter en rang global, puis en rang local a
  l'interieur. Relais a 2 sauts, replication anti-blocage apres 30 min sans
  progres, admission restreinte des buffers pleins a 80 %, epoques
  optionnelles (`epoch_s`). Les Bloom, `rankCap`, SOS et RSSI ne sont pas
  modelises (instance partagee = vues exactes, pas d'attaquant). Avec
  `random_waypoint`, les amis ne se deplacent pas ensemble : la bulle
  apporte peu tant qu'un modele de mobilite de groupe n'existe pas.
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
  (defaut 16 o) mais pas de bande passante (le budget de lien du moteur ne
  le voit pas). Pense pour une topologie connexe : en festival clairseme,
  la livraison chute par rapport aux algos DTN, c'est attendu.

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
     avec tous les noeuds (ex. `routing/bubble_f.py` y genere son graphe
     d'amis).
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
