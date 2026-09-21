# Festival BLE Mesh Simulator

Simulateur SimPy de messagerie opportuniste (mesh MANET) via Bluetooth
Low Energy entre les participants d'un festival.

## Installation

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

## Lancer une simulation

    python main.py

Le rapport est affiche dans le terminal et ecrit dans
`rapport_simulation.txt`.

### Options CLI

    python main.py --routing epidemic --beacons 6 --duration 3600 \
        --num-festivaliers 200 --seed 42 --output rapport_simulation.txt

Options disponibles :
- `--routing` : `epidemic` (defaut), `spray_wait`, `prophet` ou
  `beacon_priority` (un seul choix a la fois, pas de `|`)
- `--beacons N` : nombre de bornes (0 = desactivees, defaut)
- `--beacon-placement` : `grid` (defaut) ou `manual`
- `--duration`, `--num-festivaliers`, `--seed`, `--output`
- `--spray-initial-copies` : propre a `spray_wait` (defaut 8)

## Comparer les algorithmes

    python scripts/compare_algorithms.py --seed 42 --duration 3600 \
        --num-festivaliers 200 --beacon-count 6 [--csv comparaison.csv]

Lance automatiquement la matrice {epidemic, spray_wait, prophet,
beacon_priority} x {avec/sans bornes} avec le meme seed pour chaque run
(comparabilite equitable) et affiche un tableau comparatif
(taux de livraison, latence, sauts, overhead, energie, drops).

## Lancer les tests

    pytest

## Realisme du transfert BLE et surcharge reseau

Le moteur reseau (`src/festival_ble_sim/network.py`) modelise, en plus de
la portee radio :
- un **debit limite par lien et par tick** (`BleConfig.transfer_rate_bytes_per_s`) :
  un message qui ne rentre pas dans le budget reste en buffer et retente
  au tick suivant ;
- une **limite de connexions BLE simultanees** (`max_concurrent_links`,
  defaut 6, realiste pour un smartphone) — au-dela, les contacts les plus
  proches sont prioritaires ;
- une **perte de paquets probabiliste**, dont la probabilite croit avec le
  nombre de contacts simultanes (surcharge en foule dense) ;
- un **backhaul borne-a-borne quasi instantane** (WiFi/filaire simule),
  actif automatiquement des que 2 bornes ou plus sont presentes, hors
  contraintes de portee/debit/perte du lien BLE.

Ces effets sont visibles dans le rapport via `Messages perdus (buffer)`,
`Paquets perdus (radio)` et `Transmissions backhaul`.

## Algorithmes de routage disponibles

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

   Seule `decide()` est obligatoire. Deux hooks optionnels (no-op par
   defaut) sont disponibles :
   - `on_delivered(message, holder)` — appele quand `message` vient
     d'atteindre sa destination.
   - `on_forward(message, holder, contact, forwarded_copy)` — appele juste
     apres qu'une copie independante (`forwarded_copy`) a ete creee et
     stockee chez `contact`. Utile pour un etat par-copie asymetrique
     (ex. `routing/spray_and_wait.py` y repartit les copies restantes
     entre holder et contact).

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
     et ajoute `"mon_algo"` a la liste `choices` de `--routing`.
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
  (implemente `RoutingAlgorithm`, avec les hooks optionnels `on_delivered`
  et `on_forward`).
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
