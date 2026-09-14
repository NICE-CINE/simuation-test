# Simulateur de messagerie BLE en festival (mesh MANET) — Design, étape 1

Date : 2026-09-14
Statut : validé par l'utilisateur, en attente de plan d'implémentation

## 1. Objectif

Simuler l'échange de messages via Bluetooth Low Energy (BLE) entre les
participants d'un festival, en l'absence d'infrastructure réseau
classique (mesh MANET). Le but de cette première étape est de poser
une **architecture modulaire, typée et testable**, sur laquelle on
pourra ensuite brancher, tester et comparer différents algorithmes de
routage opportuniste et différents modèles de mobilité.

Cette étape ignore délibérément le prototype monolithique précédent
(`main.py`, ~350 lignes, `CONFIG` en dict, routage en switch statique)
: c'est une reconception complète, pas un refactor.

### Livrables de cette étape

- Architecture de base (interfaces + modèles de données).
- Boucle principale SimPy : mobilité spatiale + détection de portée BLE.
- Squelette de la stratégie de routage avec un algorithme naïf
  (Epidemic Routing).
- Modèle d'énergie simple avec déplétion de batterie.
- Rapport de simulation (delivery ratio, latence, overhead, coût
  énergétique).
- Suite de tests pytest sur la logique pure (pas de simulation
  complète en test).

### Hors scope (étapes futures)

- Algorithmes de routage avancés (Spray & Wait, PRoPHET, scoring
  personnalisé) — seuls les points d'injection sont préparés.
- Modèles de mobilité alternatifs (attraction vers une scène, densité
  de foule) — seul le point d'injection est préparé.
- Comparaison automatisée multi-algorithmes / multi-scénarios.
- Visualisation (carte, replay).
- Persistance du rapport en JSON / export structuré (le rapport reste
  une dataclass interne + un rendu texte pour l'instant).

## 2. Environnement projet

- Package Python en `src-layout`, nom `festival_ble_sim`.
- `pyproject.toml` (dépendances : `simpy`, `numpy` ; dev :
  `pytest`).
- `venv` dédié.
- Dépôt git initialisé (`git init` fait), commits au fil des étapes.
- Python cible : 3.9+ (système actuel = 3.9.6).

## 3. Structure du package

```
simu/
├── pyproject.toml
├── README.md
├── main.py                      # point d'entrée CLI
├── src/
│   └── festival_ble_sim/
│       ├── __init__.py
│       ├── config.py             # dataclasses de configuration
│       ├── models.py             # Message, Position, enums
│       ├── spatial.py            # SpatialGrid
│       ├── mobility/
│       │   ├── __init__.py
│       │   ├── base.py           # ABC MobilityModel
│       │   └── random_waypoint.py
│       ├── routing/
│       │   ├── __init__.py
│       │   ├── base.py           # ABC RoutingAlgorithm + RoutingDecision
│       │   └── epidemic.py       # EpidemicRouting (algo naïf de référence)
│       ├── energy.py             # EnergyModel, EnergyConfig
│       ├── nodes.py              # BaseNode (ABC), MobileNode, BeaconNode
│       ├── beacons.py            # stratégies de placement des bornes
│       ├── network.py            # moteur de contacts BLE (process SimPy)
│       ├── traffic.py            # générateur de trafic (Poisson)
│       ├── metrics.py            # MetricsCollector + SimulationReport
│       └── simulation.py         # orchestrateur : run_simulation(config)
└── tests/
    ├── test_spatial.py
    ├── test_mobility.py
    ├── test_routing.py
    ├── test_energy.py
    ├── test_traffic.py
    └── test_metrics.py
```

`main.py` reste le point d'entrée exécutable (`python main.py`) : il
construit une `SimulationConfig`, appelle
`festival_ble_sim.simulation.run_simulation(config)`, puis affiche /
écrit le rapport.

## 4. Modèle de données central (`models.py`)

```python
@dataclass
class Position:
    x: float
    y: float

@dataclass
class Message:
    msg_id: int
    src_id: int
    dst_id: int
    size_bytes: int
    creation_time: float
    ttl_s: float
    hops: int = 0
    # Bac à sable pour l'état propre à un algorithme de routage
    # (ex: Spray & Wait y stockera "copies_left") — garde le contrat
    # de base du message indépendant de l'algorithme utilisé.
    routing_state: Dict[str, Any] = field(default_factory=dict)
```

`Message` respecte exactement les champs demandés dans le cahier des
charges (ID unique, timestamp de création, émetteur, destinataire,
taille, hops), sans rien de spécifique à un algorithme particulier.

## 5. Configuration (`config.py`)

Une dataclass racine `SimulationConfig`, composée de sous-dataclasses
par thème. Un seul objet à instancier et à passer partout ; modifier
la taille du festival = `config.area`, désactiver les bornes =
`config.beacons.count = 0`.

```python
@dataclass(frozen=True)
class AreaConfig:
    width_m: float = 500.0
    height_m: float = 500.0

@dataclass(frozen=True)
class BleConfig:
    phone_range_m: float = 30.0
    beacon_range_m: float = 60.0
    transfer_rate_bytes_per_s: float = 10_000.0
    contact_check_interval_s: float = 1.0

@dataclass(frozen=True)
class MobilityConfig:
    speed_min_mps: float = 0.5
    speed_max_mps: float = 1.4
    pause_probability: float = 0.3
    pause_duration_range_s: Tuple[float, float] = (10.0, 60.0)
    tick_interval_s: float = 1.0

@dataclass(frozen=True)
class TrafficConfig:
    mean_interval_s: float = 5.0           # process de Poisson
    payload_size_range_bytes: Tuple[int, int] = (20, 512)
    message_ttl_s: float = 1800.0

@dataclass(frozen=True)
class EnergyConfig:
    initial_battery_mah: float = 2000.0
    tx_cost_mah_per_event: float = 0.02
    tx_cost_mah_per_byte: float = 1e-4
    rx_cost_mah_per_event: float = 0.01
    rx_cost_mah_per_byte: float = 5e-5

@dataclass(frozen=True)
class BeaconConfig:
    count: int = 0
    placement: str = "grid"    # "grid" | "manual"
    manual_positions: Optional[List[Tuple[float, float]]] = None
    unlimited_power: bool = True

@dataclass
class SimulationConfig:
    duration_s: float = 3600.0
    num_festivaliers: int = 200
    node_buffer_capacity: int = 100
    random_seed: Optional[int] = 42
    area: AreaConfig = field(default_factory=AreaConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    mobility: MobilityConfig = field(default_factory=MobilityConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    beacons: BeaconConfig = field(default_factory=BeaconConfig)

    def __post_init__(self) -> None:
        # Validation minimale au démarrage : dimensions positives,
        # au moins un festivalier, fourchette de payload cohérente.
        ...
```

## 6. Index spatial (`spatial.py`)

`SpatialGrid` : grille de cellules (taille de cellule = portée BLE la
plus grande présente dans la config) permettant de récupérer les
voisins d'un nœud en temps proche de O(1) plutôt qu'en O(n) par scan
complet — nécessaire pour rester utilisable avec plusieurs centaines
ou milliers de nœuds mobiles. Deux opérations : `update(node,
old_position)` (ré-indexation après déplacement) et
`get_nearby(node, radius) -> List[BaseNode]` (candidats dans le rayon,
filtrés par distance euclidienne exacte).

## 7. Mobilité (`mobility/`)

```python
class MobilityModel(ABC):
    @abstractmethod
    def initial_position(self, area: AreaConfig) -> Position: ...

    @abstractmethod
    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        """Calcule la nouvelle position après dt secondes.
        >>> POINT D'INJECTION : logique spatiale/mathématique perso
        (attraction vers une scène, densité de foule, zones interdites...)
        """
        ...
```

`random_waypoint.py` fournit `RandomWaypointMobility` : choix d'un
waypoint aléatoire dans la zone, déplacement à vitesse constante
tirée dans `[speed_min_mps, speed_max_mps]`, pause aléatoire à
l'arrivée selon `pause_probability` / `pause_duration_range_s`, nouveau
waypoint ensuite. `MobileNode` délègue entièrement son déplacement à
l'instance de `MobilityModel` injectée — il ne connaît aucun détail du
modèle utilisé.

## 8. Routage (`routing/`)

```python
class RoutingDecision(Enum):
    FORWARD = auto()   # transférer une copie au contact
    IGNORE = auto()    # ne rien faire

class RoutingAlgorithm(ABC):
    @abstractmethod
    def decide(
        self, message: Message, holder: "BaseNode", contact: "BaseNode"
    ) -> RoutingDecision:
        """holder possède déjà `message` ; contact ne l'a pas encore.
        >>> POINT D'INJECTION : tes propres algos de routage
        (Spray & Wait, PRoPHET, scoring basé sur les bornes...)
        """
        ...

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        """Hook optionnel, ex: purger les copies après livraison."""
        pass
```

`epidemic.py` fournit `EpidemicRouting` : implémentation naïve de
référence — `decide()` retourne `FORWARD` dès que le contact n'a pas
déjà le message (flooding). Sert de modèle minimal pour écrire un
nouvel algorithme.

## 9. Nœuds (`nodes.py`)

`BaseNode` (ABC) porte : `id`, `position`, `radio_range`, `buffer:
Dict[int, Message]` (capacité `node_buffer_capacity`, éviction FIFO du
plus ancien si plein), `battery_mah`, `is_active` (passe à `False`
quand `battery_mah <= 0`).

- `MobileNode(BaseNode)` : + `mobility: MobilityModel`, process SimPy
  de déplacement (`step()` à chaque tick), génère et consomme des
  messages en tant que festivalier.
- `BeaconNode(BaseNode)` : position fixe, `battery_mah = inf` par
  défaut si `beacons.unlimited_power`, sinon même modèle d'énergie que
  les nœuds mobiles.

## 10. Placement des bornes (`beacons.py`)

Fonction `place_beacons(config: SimulationConfig) -> List[Position]` :
mode `"grid"` (disposition régulière calculée à partir de
`beacons.count` et de la zone), mode `"manual"` (convertit chaque
tuple `(x, y)` de `beacons.manual_positions` en `Position`). Simple
fonction (pas un Strategy complet) — le point d'injection pour un
placement stratégique personnalisé est ici, commenté.

## 11. Trafic (`traffic.py`)

Process SimPy : intervalle entre créations de messages tiré d'une loi
exponentielle de moyenne `traffic.mean_interval_s` (processus de
Poisson), source et destination tirées aléatoirement parmi les
festivaliers actifs (hors bornes), taille tirée uniformément dans
`traffic.payload_size_range_bytes`. Message inséré dans le buffer de
la source et transmis au `MetricsCollector` pour comptage des créations.

## 12. Moteur de contacts BLE (`network.py`)

Process SimPy périodique (`ble.contact_check_interval_s`), volontairement
découplé de `mobility.tick_interval_s` : le déplacement peut être
recalculé plus souvent (fluidité de trajectoire) que le scan de
voisinage (coût en calcul), sans que les deux fréquences soient liées.

1. Purge des messages expirés (TTL) dans le buffer de chaque nœud actif.
2. Pour chaque nœud actif ayant des messages en buffer, récupère les
   voisins via `SpatialGrid.get_nearby(node, node.radio_range)`.
3. Pour chaque voisin actif sans le message :
   - si `voisin.id == message.dst_id` → livraison directe,
     `MetricsCollector.record_delivery(...)`.
   - sinon → délègue à `routing_algorithm.decide(message, holder,
     contact)`.
4. Sur `FORWARD` : incrémente `message.hops`, applique le coût
   d'énergie tx (holder) et rx (contact) via `EnergyModel`, journalise
   la transmission pour le calcul de l'overhead, insère la copie dans
   le buffer du contact (éviction FIFO si plein).

Ce module ne connaît ni les détails de l'algorithme de routage, ni
ceux du modèle de mobilité — seulement la géométrie (via `SpatialGrid`)
et l'interface `RoutingAlgorithm`.

## 13. Énergie (`energy.py`)

```python
class EnergyModel:
    def __init__(self, config: EnergyConfig): ...
    def cost_of_tx(self, size_bytes: int) -> float: ...
    def cost_of_rx(self, size_bytes: int) -> float: ...
```

Chaque nœud porte `battery_mah`, décrémentée par `network.py` à chaque
transmission/réception. Quand `battery_mah <= 0` →
`node.is_active = False` : le moteur de contacts ignore ensuite ce
nœud (ni émission ni réception), rendant l'effet visible dans le taux
de livraison final. Les bornes sont sur secteur par défaut
(`unlimited_power=True`), configurable individuellement.

## 14. Métriques et rapport (`metrics.py`)

`MetricsCollector`, alimenté en direct par `network.py` et
`traffic.py`, calcule en fin de simulation :

- **Delivery ratio** = messages livrés / messages créés.
- **Latence** moyenne + p95 (création → livraison).
- **Overhead** = nombre total de copies transmises / messages livrés.
- **Coût énergie** = mAh consommés (total + moyenne par nœud), nombre
  de nœuds morts (batterie épuisée) en fin de simulation.
- **Nombre moyen de sauts** pour les messages livrés.

Résultat exposé comme dataclass `SimulationReport` (données), rendu en
texte par une fonction séparée (`metrics.format_report(report) ->
str`) — permet de réutiliser la donnée brute plus tard (export JSON,
comparaison multi-algorithmes) sans dépendre du format texte.

## 15. Orchestration (`simulation.py`)

`run_simulation(config: SimulationConfig) -> SimulationReport` :

1. Crée l'`Environment` SimPy et la `SpatialGrid`.
2. Place les bornes (`beacons.place_beacons`), crée les `BeaconNode`.
3. Crée les `MobileNode` (position initiale + `MobilityModel` injecté).
4. Instancie l'algorithme de routage (passé en paramètre ou choisi par
   défaut = `EpidemicRouting`) et le partage entre tous les nœuds.
5. Démarre les process SimPy : mobilité par nœud, `traffic_generator`,
   `network engine`.
6. `env.run(until=config.duration_s)`.
7. Construit et retourne le `SimulationReport` via `MetricsCollector`.

## 16. Tests (pytest)

Tests ciblés sur la logique pure, sans lancer de simulation SimPy
complète :

- `test_spatial.py` : voisins retournés dans le rayon, exclus hors
  rayon, comportement aux bords de la zone.
- `test_mobility.py` : `RandomWaypointMobility.step()` reste dans les
  bornes de la zone, avance à la vitesse attendue sur `dt`.
- `test_routing.py` : `EpidemicRouting.decide()` → `FORWARD` si le
  contact n'a pas le message ; comportement du hook `on_delivered`.
- `test_energy.py` : coût tx/rx calculé correctement ; nœud passe
  `is_active=False` à batterie nulle.
- `test_traffic.py` : intervalles suivent une loi exponentielle (test
  statistique tolérant, pas un test exact) ; taille de payload dans la
  fourchette configurée.
- `test_metrics.py` : delivery ratio / latence / overhead calculés
  correctement sur un scénario construit à la main (pas de run SimPy
  réel).

## 17. Gestion des erreurs / cas limites

Pas de gestion défensive superflue : on fait confiance à la config une
fois validée au démarrage (`SimulationConfig.__post_init__` vérifie
les bornes évidentes — dimensions > 0, `num_festivaliers > 0`,
fourchette de payload croissante). Le seul mécanisme de gestion
d'erreur métier nécessaire est l'éviction FIFO du buffer de nœud
lorsqu'il atteint `node_buffer_capacity`.
