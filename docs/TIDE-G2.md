# TIDE-G2 — TIDE-G + position dans l'ACK, abandon de l'indice et GPS réaliste

TIDE-G2 n'est pas un nouvel algorithme : c'est **TIDE-G avec cinq ajouts activables un par un**, plus deux réalismes côté moteur (échec du fix GPS, rafales de messages). Tous les ajouts sont **désactivés par défaut** : `tide_g` donne exactement les mêmes résultats qu'avant. `tide_g2` est le preset qui active la combinaison retenue.

Ce document suppose connus TIDE (`docs/algorithmes/tide.md`) et TIDE-G (`docs/TIDE-G.md`). Il ne décrit que le delta.

> **Statut** : implémenté (`routing/tide_g.py`, `TIDE_G2_KWARGS`), 11 tests dans `tests/test_routing_tide_g2.py`. `tide_g` et `tide` sont bit-à-bit identiques avant et après le changement (run de référence : 150 festivaliers, 15 min, réponses à 50 %, mobilité `poi`). Une première campagne (81 simulations, §5, faite sur un prototype) a servi à choisir le preset.

---

## 1. Ce que TIDE-G2 ajoute

| # | Ajout | Paramètre | Faiblesse de TIDE-G visée | Dans `tide_g2` |
|---|---|---|---|---|
| 1 | Position du destinataire dans l'ACK | `ack_hint` | Un indice n'existe que si le destinataire a **écrit** récemment à la source | oui |
| 2 | Abandon de l'indice après un silence | `geo_giveup_s` | Des copies « zone » restent enfermées dans un disque que le destinataire a quitté | oui (180 s) |
| 3 | Premier spray réduit quand l'indice est frais | `hint_scaled_tokens` | TIDE-G sème autant de copies au départ, qu'on sache ou non où est le destinataire | **non** (perd des livraisons, §5) |
| 4 | Fusion d'indices dans le buffer d'un relais | `relay_hint_merge` | Deux messages vers la même personne, portés par le même relais, ignorent l'indice le plus frais | **non** (ablation vie privée) |
| 5 | Fix GPS facturé à l'envoi et à l'ACK | `charge_message_fixes` | Le fix pris à la création d'un message est gratuit dans le simulateur | oui |
| M1 | Échec du fix GPS | `GpsConfig.fix_failure_probability` | Un fix réussit toujours, instantanément | moteur, 0 par défaut |
| M2 | Rafales de messages | `TrafficConfig.followup_probability` | Le trafic n'a pas de « relances » vers le même destinataire, alors que c'est là que l'ajout 1 sert | moteur, 0 par défaut |

Principe directeur, hérité de TIDE-G : **sans indice utilisable, on retombe exactement sur TIDE**. Le score géographique de TIDE-G (jamais en dessous de l'utilité TIDE) n'est pas modifié, et la réinjection de TIDE reste le filet de sécurité.

---

## 2. Spécification

### 2.1 Position du destinataire dans l'ACK (`ack_hint`)

**Constat.** Dans TIDE-G, Léa n'a un indice pour Paul que si Paul lui a écrit dans les 15 dernières minutes. Sans réponses, environ 3 % des messages ont un indice ; avec 50 % de réponses, environ 24 % (`docs/TIDE-G.md` §6).

**Ajout.** Quand Paul reçoit un message de Léa, son ACK transporte sa propre position, **chiffrée pour Léa**. Léa obtient ainsi une position fraîche de Paul à chaque message livré, sans que Paul ait à répondre. Le prochain message de Léa vers Paul part avec un indice.

**Vie privée.** C'est toujours le destinataire qui révèle sa propre position, et seulement à son correspondant : la règle « destinataire seul » de TIDE-G est respectée. En revanche, Paul révèle désormais sa position à **toute personne qui lui écrit** (pas seulement à celles à qui il écrit). Le réglage produit doit couvrir les deux sens, ou en avoir deux : « partager ma position avec les personnes à qui j'écris » et « … qui m'écrivent ».

**Modèle dans le simulateur.**

- TIDE purge l'ACK instantanément dans tout le réseau (simplification existante). La position, elle, ne revient pas instantanément : elle est rendue disponible chez la source après `ack_hint_delay_factor × (latence aller)`. Valeur par défaut 1,0 : le retour prend autant de temps que l'aller.
- Le fix du destinataire réutilise son fix périodique s'il a moins de `fix_max_age_s` (**avec l'horodatage de ce fix**, pas celui de la livraison), sinon il prend un fix ponctuel (§2.5).
- La position arrive dans `source.known_positions[dst]` via `record_known_position` (la plus récente gagne). Le moteur l'utilise ensuite tout seul pour remplir `dst_position` des messages suivants, et le rafraîchissement d'indice de TIDE-G (`refresh_hint`) met à jour la copie fantôme de la source.

**Limite.** L'ACK n'aide que si Léa **réécrit** à Paul dans les 15 minutes. Dans un échange alterné (Léa, Paul, Léa…), chaque message porte déjà la position de son émetteur : l'ACK apporte surtout une position plus fraîche. Le vrai gain apparaît sur les **relances** (Léa écrit deux fois de suite), d'où le modèle de rafales (§2.7).

### 2.2 Abandon de l'indice après un silence (`geo_giveup_s`)

**Constat.** Une copie « zone » de TIDE-G ne se partage qu'avec des relais **dans le disque** de l'indice. Si le destinataire a quitté le disque, ces copies tournent en rond.

**Ajout.** Passé `geo_giveup_s` après la création du message, `_hint()` renvoie `None` pour toutes les copies. Le message redevient un message TIDE pur :

- la restriction « zone » tombe (`_spray_ok` accepte tout relais) ;
- les règles géographiques de focus et de partage des jetons s'éteignent ;
- les porteurs arrêtent de prendre des fixes pour ce message (`_needs_gps`).

La décision est **décentralisée** : chaque copie connaît `creation_time`, aucun message de contrôle n'est nécessaire. Valeur de départ : 180 s, alignée sur la première réinjection de TIDE (le budget de copies remonte au même moment).

Statistique associée : `delivered_after_giveup`, le nombre de messages à indice livrés **après** l'abandon. Pour savoir si l'abandon coupe trop tôt, comparer la livraison avec et sans abandon à graine égale : ce compteur seul ne suffit pas, puisque ces messages arrivent quand même.

### 2.3 Premier spray réduit quand l'indice est frais (`hint_scaled_tokens`)

**Constat.** TIDE fixe le nombre de copies initial `L0` d'après la densité locale, sans tenir compte de ce qu'on sait du destinataire.

**Ajout.** À la source, au premier routage, si le message a un indice :

```
k0 = max(l_min, round(L0 × min(1, (r(h) / r_ref)²)))
```

avec `r(h)` le rayon d'incertitude de TIDE-G et `r_ref` = `hint_tokens_ref_m` = 120 m, soit le rayon d'un indice de 5 minutes. L'aire à couvrir croît en r², le budget aussi.

| Âge de l'indice | r(h) | Copies initiales (L0 = 12) |
|---|---|---|
| 0 min | 30 m | 2 (`l_min`) |
| 2 min | 66 m | 4 |
| 5 min et plus | ≥ 120 m | 12 (inchangé) |

**Seul le premier spray est réduit** : `routing_state["l0"]` garde la valeur de TIDE. Si l'indice était faux, les réinjections (180, 360, 1200 s) restaurent un budget TIDE complet.

**Résultat** : cet ajout perd de la livraison dans les trois scénarios testés (§5). Il reste disponible pour les ablations, mais il est **exclu du preset**.

### 2.4 Fusion d'indices dans le buffer d'un relais (`relay_hint_merge`)

**Ajout.** Avant de router un message qu'il relaie, un relais regarde les autres messages **de son propre buffer** destinés à la même personne. Si l'un porte un indice plus récent, il le recopie.

**Vie privée.** Le relais ne réutilise que des indices qu'il porte déjà en clair, et n'enregistre rien d'autre : la règle « jamais où on a croisé quelqu'un » tient. Mais l'indice fourni par Paul à Léa sert désormais aussi à guider le message de Marc vers Paul. C'est un glissement par rapport à « seul le correspondant s'en sert ». C'est pourquoi l'ajout est **exclu du preset** et réservé à une ablation : il mesure ce que cette entorse rapporterait.

### 2.5 Fix GPS facturé à l'envoi et à l'ACK (`charge_message_fixes`)

Dans le moteur, `message.src_position` est lu gratuitement à la création. TIDE-G2 facture un **fix ponctuel** :

- à la source, au premier routage du message ;
- au destinataire, quand il construit l'ACK (si `ack_hint`).

Coût : `gps_current_ma × message_fix_s / 3600` mAh, avec `message_fix_s` = 5 s (fix à froid court). Si le nœud a déjà un fix périodique de moins de `fix_max_age_s`, il le réutilise et ne paie rien. Un fix ponctuel réussi devient le fix courant du nœud : il participe aux règles géographiques pendant 60 s.

### 2.6 Échec du fix GPS (moteur, `GpsConfig.fix_failure_probability`)

Nouvelle méthode `BaseNode.gps_fix() -> Optional[Position]` : renvoie `None` avec la probabilité configurée, sinon `gps_position()`. Elle remplace `gps_position()` partout où un **fix** est pris :

- création d'un message et d'une réponse (`traffic.py`) : sans fix, `src_position = None` ;
- fixes périodiques de TIDE-G : l'énergie est payée même en cas d'échec, mais le fix n'est pas enregistré ;
- fixes ponctuels de TIDE-G2.

`gps_position()` reste disponible tel quel. Le tirage aléatoire n'a lieu que si la probabilité est > 0 : avec 0, la séquence de nombres aléatoires est inchangée et tous les runs existants sont identiques. Bornes : jamais d'échec.

Non modélisé : la corrélation des échecs (zones couvertes, foule compacte) et la latence d'acquisition. À ajouter si les mesures terrain montrent qu'ils comptent.

### 2.7 Rafales de messages (moteur, `TrafficConfig.followup_probability`)

Après chaque message spontané, l'émetteur relance **le même destinataire** avec la probabilité `followup_probability`, après un délai tiré dans `followup_delay_range_s` (10–120 s par défaut). La chaîne est géométrique : une rafale compte en moyenne `1 / (1 − p)` messages.

La chaîne s'arrête dès que l'émetteur ou le destinataire n'est plus actif au moment d'une relance.

C'est la situation typique « t'es où ? » puis « on est devant la grande scène » une minute après. Sans elle, l'ajout 1 ne peut presque rien montrer.

Le générateur aléatoire des rafales est seedé à part (`random.Random(f"{seed}-followup")`, déterministe) et n'existe que si p > 0 : activer les rafales ne décale aucun autre tirage.

### 2.8 Paramètres

| Paramètre | Où | Défaut | Preset `tide_g2` |
|---|---|---|---|
| `ack_hint` | `TideGRouting` | `False` | `True` |
| `ack_hint_delay_factor` | `TideGRouting` | 1,0 | 1,0 |
| `geo_giveup_s` | `TideGRouting` | `None` (jamais) | 180 s |
| `hint_scaled_tokens` | `TideGRouting` | `False` | `False` |
| `hint_tokens_ref_m` | `TideGRouting` | 120 m | 120 m |
| `relay_hint_merge` | `TideGRouting` | `False` | `False` |
| `charge_message_fixes` | `TideGRouting` | `False` | `True` |
| `message_fix_s` | `TideGRouting` | 5 s | 5 s |
| `fix_failure_probability` | `GpsConfig` | 0,0 | — (scénario) |
| `followup_probability` | `TrafficConfig` | 0,0 | — (scénario) |
| `followup_delay_range_s` | `TrafficConfig` | (10, 120) s | — |
| Paramètres TIDE et TIDE-G | inchangés | | |

CLI (`main.py` et `scripts/compare_algorithms.py`) : `--routing tide_g2`, `--followup-probability`, `--gps-fix-failure`.

---

## 3. Implémentation dans le simulateur

Le détail ci-dessous permet de relire le code. Les conventions du dépôt sont respectées : Python 3.9, pas de docstrings, commentaires uniquement pour un « pourquoi » non évident.

### 3.1 Ordre des changements

1. Moteur : `config.py`, `nodes.py`, `simulation.py`, `traffic.py` (§3.2). Vérifier que tous les tests passent et qu'un run TIDE-G de référence est identique.
2. `routing/tide_g.py` (§3.3). Vérifier à nouveau l'identité de `tide_g`.
3. Enregistrement dans les deux scripts (§3.4).
4. Tests (§4).

### 3.2 Moteur

`config.py` :

```python
@dataclass(frozen=True)
class TrafficConfig:
    ...
    # Bursts: after each spontaneous message, the sender writes again to the
    # same destination with this probability (geometric chain), after a
    # delay drawn from followup_delay_range_s. 0.0 = off (previous behavior).
    followup_probability: float = 0.0
    followup_delay_range_s: Tuple[float, float] = (10.0, 120.0)


@dataclass(frozen=True)
class GpsConfig:
    noise_std_m: float = 5.0
    # Probability that a fix attempt yields nothing (indoors, cold start,
    # crowd). Drawn only when > 0, so runs without it are unchanged.
    fix_failure_probability: float = 0.0

# dans SimulationConfig.__post_init__
        if not 0.0 <= self.traffic.followup_probability < 1.0:
            raise ValueError("followup_probability must be in [0, 1)")
        followup_lo, followup_hi = self.traffic.followup_delay_range_s
        if followup_lo < 0 or followup_hi < followup_lo:
            raise ValueError("followup_delay_range_s must satisfy 0 <= lo <= hi")
        ...
        if not 0.0 <= self.gps.fix_failure_probability < 1.0:
            raise ValueError("gps fix_failure_probability must be in [0, 1)")
```

`nodes.py` :

```python
class BaseNode:
    def __init__(...):
        ...
        self.gps_rng: Optional[random.Random] = None
        self.gps_fix_failure_probability = 0.0

    def gps_fix(self) -> Optional[Position]:
        if (
            self.gps_fix_failure_probability > 0
            and self.gps_rng is not None
            and self.gps_rng.random() < self.gps_fix_failure_probability
        ):
            return None
        return self.gps_position()
```

`simulation.py` :

```python
    mobile_nodes: Dict[int, MobileNode] = {}
    msg_id_counter = itertools.count(1)
    # Seeded apart from rng (str seeds are deterministic), so enabling
    # followups never shifts any existing draw.
    followup_rng = (
        random.Random(f"{config.random_seed}-followup") if config.traffic.followup_probability > 0 else None
    )
    for _ in range(config.num_festivaliers):
        ...
        traffic_rng = random.Random(rng.randrange(1 << 30))
        env.process(traffic_process(
            env, mobile, mobile_nodes, config.traffic, metrics, msg_id_counter, traffic_rng, followup_rng
        ))
    ...
    for node_id, mobile in mobile_nodes.items():
        ...
        mobile.gps_rng = gps_rng
        mobile.gps_fix_failure_probability = config.gps.fix_failure_probability
```

`traffic.py` :

```python
def traffic_process(env, node, nodes, config, metrics, id_generator, rng,
                    followup_rng: Optional[random.Random] = None):
    ...
        message = generate_message(
            next(id_generator), env.now, node.id, dst_id, config, rng,
            src_position=node.gps_fix(),
            dst_known=node.known_positions.get(dst_id),
        )
        node.store_message(message)
        metrics.record_creation(message)
        if followup_rng is not None and config.followup_probability > 0:
            env.process(followup_process(env, node, dst_id, nodes, config, metrics, id_generator, followup_rng))


def followup_process(env, node, dst_id, nodes, config, metrics, id_generator, rng):
    while rng.random() < config.followup_probability:
        delay_s = rng.uniform(*config.followup_delay_range_s)
        yield from reply_process(env, node, dst_id, delay_s, nodes, config, metrics, id_generator, rng)

# reply_process : src_position=node.gps_fix() au lieu de node.gps_position()
```

`followup_process` réutilise `reply_process`, qui fait exactement « envoyer à `dst_id` après un délai si les deux sont encore actifs ».

### 3.3 `routing/tide_g.py`

En-tête et preset :

```python
from .tide import TideRouting, _L0, _REINJECTIONS, _TOKENS

_ZONE = "zone"
_GEO_L0 = "geo_l0"

# TIDE-G2 preset: hint_scaled_tokens lost deliveries and relay_hint_merge
# bends the privacy rule, so both stay ablations (docs/TIDE-G2.md §5).
TIDE_G2_KWARGS = dict(ack_hint=True, geo_giveup_s=180.0, charge_message_fixes=True)
```

Constructeur, nouveaux paramètres (après `refresh_hint`) :

```python
        ack_hint: bool = False,
        ack_hint_delay_factor: float = 1.0,
        geo_giveup_s: Optional[float] = None,
        hint_scaled_tokens: bool = False,
        hint_tokens_ref_m: float = 120.0,
        relay_hint_merge: bool = False,
        charge_message_fixes: bool = False,
        message_fix_s: float = 5.0,
        **tide_kwargs,
    ) -> None:
        ...
        if ack_hint_delay_factor < 0 or hint_tokens_ref_m <= 0 or message_fix_s < 0:
            raise ValueError("ack_hint_delay_factor and message_fix_s must be >= 0, hint_tokens_ref_m > 0")
        if geo_giveup_s is not None and geo_giveup_s <= 0:
            raise ValueError("geo_giveup_s must be None or > 0")
        ...  # self._ack_hint = ack_hint, etc.
        # (available_at, src_id, dst_id, dst position, fix time): the ACK is
        # purged network-wide instantly, but its position must still travel back.
        self._pending_ack_hints: List[Tuple[float, int, int, Position, float]] = []
        self._ack_hint_times: Dict[Tuple[int, int], float] = {}
        self.hint_stats = {
            "routed": 0, "hinted": 0, "delivered": 0, "delivered_hinted": 0, "gps_fixes": 0,
            "hinted_by_ack": 0, "ack_hints_sent": 0, "ack_hints_received": 0, "message_fixes": 0,
            "merged_hints": 0, "scaled_tokens": 0, "delivered_after_giveup": 0,
        }
```

Fixes : `on_tick` livre les positions d'ACK arrivées **avant** le `return` anticipé du tour GPS, et utilise `gps_fix()` :

```python
    def on_tick(self, now, neighbors_by_node):
        super().on_tick(now, neighbors_by_node)
        self._flush_ack_hints(now)
        if now < self._next_gps_round:
            return
        self._next_gps_round = now + self._gps_period_s
        fix_mah = self._gps_current_ma * self._gps_period_s / 3600.0
        for nid in neighbors_by_node:
            node = self._nodes.get(nid)
            if node is None or node.is_beacon:
                continue
            if self._needs_gps(node, now):
                fix = node.gps_fix()
                if fix is not None:
                    self._fixes[nid] = (fix, now)
                node.consume_energy(fix_mah)
                self.hint_stats["gps_fixes"] += 1

    def _message_fix(self, node, now) -> Optional[Tuple[Position, float]]:
        # One-shot fix for a send or an ACK: reuses a fresh periodic fix (with
        # its own, older timestamp), otherwise pays a short cold fix.
        if node.is_beacon:
            return node.position, now
        fresh = self._fixes.get(node.id)
        if fresh is not None and now - fresh[1] <= self._fix_max_age_s:
            return fresh
        fix = node.gps_fix()
        if self._charge_message_fixes:
            node.consume_energy(self._gps_current_ma * self._message_fix_s / 3600.0)
        self.hint_stats["message_fixes"] += 1
        if fix is None:
            return None
        self._fixes[node.id] = (fix, now)
        return fix, now
```

Abandon de l'indice, au début de `_hint` :

```python
        if self._geo_giveup_s is not None and now - message.creation_time > self._geo_giveup_s:
            return None
```

`_before_route` : fix facturé et attribution des indices venus d'un ACK, puis fusion et réduction du spray :

```python
        if holder.id == message.src_id and message.msg_id not in self._seen:
            self._seen.add(message.msg_id)
            self.hint_stats["routed"] += 1
            if self._charge_message_fixes:
                self._message_fix(holder, now)
            if self._hint(message, now) is not None:
                self.hint_stats["hinted"] += 1
                if message.dst_position_time == self._ack_hint_times.get((message.src_id, message.dst_id)):
                    self.hint_stats["hinted_by_ack"] += 1
        # ... refresh_hint inchangé ...
        if self._relay_hint_merge and holder.id != message.src_id:
            self._merge_buffer_hint(message, holder)
        if self._hint_scaled_tokens and holder.id == message.src_id and not state.get(_GEO_L0):
            state[_GEO_L0] = True
            self._scale_initial_tokens(message, now)
        # ... recherche locale (zone) inchangée ...

    def _merge_buffer_hint(self, message, holder):
        # Only hints the relay already carries in clear: nothing is recorded
        # about where it met anyone.
        best_time = message.dst_position_time
        best = None
        for other in holder.buffer.values():
            t = other.dst_position_time
            if other.dst_id == message.dst_id and t is not None and (best_time is None or t > best_time):
                best_time, best = t, other
        if best is not None:
            message.dst_position, message.dst_position_time = best.dst_position, best.dst_position_time
            self.hint_stats["merged_hints"] += 1

    def _scale_initial_tokens(self, message, now):
        # Shrinks the first spray only: _L0 stays TIDE's, so reinjections
        # restore a full TIDE budget if the hint turns out wrong.
        state = message.routing_state
        hint = self._hint(message, now)
        if hint is None or state[_REINJECTIONS] > 0 or state[_TOKENS] != state[_L0]:
            return
        scale = min(1.0, (hint.radius_m / self._hint_tokens_ref_m) ** 2)
        scaled = int(max(self._l_min, round(state[_L0] * scale)))
        if scaled < state[_TOKENS]:
            state[_TOKENS] = scaled
            self.hint_stats["scaled_tokens"] += 1
```

ACK : `on_delivered` n'a pas de `now` ; on prend `self._prev_tick`, l'instant du tick courant (TIDE le met à jour à la fin de son `on_tick`, qui précède toujours le traitement des contacts) :

```python
    def on_delivered(self, message, holder):
        first = message.msg_id not in self._delivered_ids
        now = self._prev_tick if self._prev_tick is not None else message.creation_time
        if first:
            self.hint_stats["delivered"] += 1
            if self._hint(message, message.creation_time) is not None:
                self.hint_stats["delivered_hinted"] += 1
                if self._geo_giveup_s is not None and now - message.creation_time > self._geo_giveup_s:
                    self.hint_stats["delivered_after_giveup"] += 1
        super().on_delivered(message, holder)
        if first and self._ack_hint:
            self._queue_ack_hint(message, now)

    def _queue_ack_hint(self, message, now):
        dst = self._nodes.get(message.dst_id)
        if dst is None:
            return
        fix = self._message_fix(dst, now)
        if fix is None:
            return
        # Return trip assumed as long as the outbound one (factor 1.0).
        available_at = now + self._ack_hint_delay_factor * max(0.0, now - message.creation_time)
        self._pending_ack_hints.append((available_at, message.src_id, message.dst_id, fix[0], fix[1]))
        self.hint_stats["ack_hints_sent"] += 1

    def _flush_ack_hints(self, now):
        if not self._pending_ack_hints:
            return
        pending = []
        for item in self._pending_ack_hints:
            available_at, src_id, dst_id, pos, fix_time = item
            if available_at > now:
                pending.append(item)
                continue
            src = self._nodes.get(src_id)
            if src is not None and src.is_active:
                src.record_known_position(dst_id, pos, fix_time)
                if src.known_positions[dst_id][1] == fix_time:
                    self._ack_hint_times[(src_id, dst_id)] = fix_time
                self.hint_stats["ack_hints_received"] += 1
        self._pending_ack_hints = pending
```

Point d'architecture : `_flush_ack_hints` écrit dans `node.known_positions`, qui appartient au moteur. C'est voulu : c'est le canal par lequel le moteur remplit `dst_position` des messages suivants, exactement comme pour une réponse. À signaler dans la section GPS de `CLAUDE.md`.

### 3.4 Enregistrement

- `main.py` : `"tide_g2": lambda args: TideGRouting(seed=args.seed, **TIDE_G2_KWARGS)` dans `ROUTING_FACTORIES` ; options `--followup-probability` et `--gps-fix-failure`, passées à `TrafficConfig(followup_probability=…)` et `GpsConfig(fix_failure_probability=…)` dans `build_config`.
- `scripts/compare_algorithms.py` : `"tide_g2": lambda: TideGRouting(**TIDE_G2_KWARGS)` dans `ALGORITHMS` ; les deux mêmes options, propagées dans `build_config`, `_run_one` et `run_matrix` comme `reply_probability`.

```bash
python main.py --routing tide_g2 --mobility poi --reply-probability 0.5 --followup-probability 0.5 \
    --duration 1800 --num-festivaliers 400
```

---

## 4. Tests (`tests/test_routing_tide_g2.py`)

| Test | Ce qu'il vérifie |
|---|---|
| `test_ack_hint_reaches_the_source_after_the_return_trip` | Livré à t = 10 s pour un message créé à 4 s : la position n'est pas là à 15 s, elle arrive à 16 s avec l'horodatage du fix |
| `test_ack_hint_is_off_by_default` | Sans `ack_hint`, la source n'apprend rien |
| `test_hint_is_dropped_after_geo_giveup` | Indice utilisable à 179 s, ignoré à 181 s |
| `test_fresh_hint_shrinks_only_the_first_spray` | Indice d'âge nul : 2 jetons, mais `l0` garde la valeur TIDE |
| `test_stale_hint_keeps_the_full_tide_budget` | Indice de 400 s : jetons = `l0` |
| `test_relay_merges_a_fresher_hint_from_its_buffer` | Le relais recopie l'indice plus récent d'un autre message vers la même personne |
| `test_relay_merge_is_off_by_default` | Sans le flag, rien n'est fusionné |
| `test_send_fix_is_charged_only_without_a_fresh_periodic_fix` | 36 mA × 5 s = 0,05 mAh sans fix frais ; 0 avec un fix périodique |
| `test_gps_fix_fails_with_its_probability_and_matches_gps_position_at_zero` | Même séquence que `gps_position()` à p = 0 ; ~50 % d'échecs à p = 0,5 |
| `test_followups_add_messages_without_changing_runs_where_they_are_off` | Les rafales ajoutent des messages |
| `test_small_festival_tide_g2_hints_messages_from_acks` | Intégration : des messages partent avec un indice venu d'un ACK |

Test de non-régression à garder en tête (fait à la main pendant le développement) : un run `tide_g` à graine fixe doit donner exactement le même rapport avant et après le patch.

---

## 5. Résultats préliminaires

Conditions : mobilité `poi`, 400 festivaliers sur le site par défaut (0,35 km², soit environ 1 140 personnes/km²), 30 min, sans bornes, graines 1 à 3. « Écart apparié » : différence de livraison avec TIDE-G **à graine égale**, moyenne ± écart-type sur les 3 graines. « Surcharge » : transmissions par message livré.

**Réponses 50 %, sans rafales** (moyenne sur 3 graines)

| Variante | Livraison | Écart vs TIDE-G (apparié) | Latence moy. | p95 | Surcharge | Énergie/nœud | Messages avec indice | dont indice venu d'un ACK |
|---|---|---|---|---|---|---|---|---|
| TIDE | 55,0 % | −2,4 ± 1,2 pts | 277 s | 1061 s | 54,3 | 4,16 mAh | 0,0 % | 0,0 % |
| TIDE-G | 57,4 % | — | 268 s | 1013 s | 59,0 | 9,56 mAh | 27,7 % | 0,0 % |
| TIDE-G + ACK | 58,1 % | +0,7 ± 1,1 pts | 266 s | 1010 s | 58,8 | 9,64 mAh | 30,2 % | 3,6 % |
| TIDE-G + abandon | 58,3 % | +0,9 ± 0,6 pts | 261 s | 1014 s | 56,0 | 9,58 mAh | 29,4 % | 0,0 % |
| TIDE-G + spray réduit | 56,4 % | −1,1 ± 0,8 pts | 271 s | 1045 s | 57,8 | 9,41 mAh | 27,1 % | 0,0 % |
| TIDE-G + fusion | 57,8 % | +0,4 ± 0,1 pts | 259 s | 997 s | 58,3 | 9,57 mAh | 28,2 % | 0,0 % |
| les quatre ajouts (1er preset) | 56,9 % | −0,5 ± 1,9 pts | 274 s | 1034 s | 56,0 | 9,41 mAh | 29,8 % | 3,7 % |
| **TIDE-G2** (ACK + abandon + fixes) | 56,7 % | −0,7 ± 1,0 pts | 263 s | 1009 s | 58,7 | 9,56 mAh | 29,5 % | 4,4 % |

**Réponses 50 % et rafales 50 %** (moyenne sur 3 graines)

| Variante | Livraison | Écart vs TIDE-G (apparié) | Latence moy. | p95 | Surcharge | Énergie/nœud | Messages avec indice | dont indice venu d'un ACK |
|---|---|---|---|---|---|---|---|---|
| TIDE | 54,9 % | −2,1 ± 2,2 pts | 273 s | 1042 s | 53,6 | 6,91 mAh | 0,0 % | 0,0 % |
| TIDE-G | 57,1 % | — | 259 s | 998 s | 57,8 | 12,86 mAh | 30,8 % | 0,0 % |
| TIDE-G + ACK | 57,3 % | +0,2 ± 2,0 pts | 253 s | 993 s | 59,6 | 13,06 mAh | 35,2 % | 11,0 % |
| TIDE-G + abandon | 56,7 % | −0,4 ± 1,0 pts | 254 s | 994 s | 56,2 | 12,56 mAh | 30,0 % | 0,0 % |
| TIDE-G + spray réduit | 55,1 % | −1,9 ± 2,2 pts | 264 s | 1019 s | 57,0 | 12,40 mAh | 29,5 % | 0,0 % |
| TIDE-G + fusion | 57,3 % | +0,3 ± 0,3 pts | 262 s | 1012 s | 58,5 | 12,98 mAh | 30,3 % | 0,0 % |
| les quatre ajouts (1er preset) | 54,6 % | −2,5 ± 2,0 pts | 261 s | 1036 s | 55,2 | 12,12 mAh | 34,2 % | 9,7 % |
| **TIDE-G2** (ACK + abandon + fixes) | 57,5 % | +0,5 ± 1,8 pts | 245 s | 964 s | 55,2 | 12,56 mAh | 35,8 % | 10,1 % |

**Rafales 50 %, sans réponses** (moyenne sur 3 graines)

| Variante | Livraison | Écart vs TIDE-G (apparié) | Latence moy. | p95 | Surcharge | Énergie/nœud | Messages avec indice | dont indice venu d'un ACK |
|---|---|---|---|---|---|---|---|---|
| TIDE | 49,1 % | −0,9 ± 1,0 pts | 333 s | 1039 s | 63,6 | 5,84 mAh | 0,0 % | 0,0 % |
| TIDE-G | 50,1 % | — | 340 s | 1067 s | 63,5 | 10,92 mAh | 5,1 % | 0,0 % |
| TIDE-G + ACK | 49,9 % | −0,1 ± 1,0 pts | 325 s | 1086 s | 67,6 | 11,22 mAh | 13,9 % | 10,4 % |
| TIDE-G + abandon | 49,9 % | −0,1 ± 0,2 pts | 331 s | 1078 s | 63,4 | 10,90 mAh | 5,1 % | 0,0 % |
| TIDE-G + spray réduit | 49,7 % | −0,4 ± 0,3 pts | 332 s | 1067 s | 64,0 | 10,91 mAh | 5,0 % | 0,0 % |
| TIDE-G + fusion | 50,1 % | +0,0 ± 0,9 pts | 338 s | 1131 s | 63,9 | 10,95 mAh | 5,0 % | 0,0 % |
| les quatre ajouts (1er preset) | 49,4 % | −0,6 ± 0,6 pts | 343 s | 1119 s | 65,1 | 10,99 mAh | 14,8 % | 11,4 % |
| **TIDE-G2** (ACK + abandon + fixes) | 50,2 % | +0,1 ± 0,7 pts | 330 s | 1094 s | 64,6 | 10,99 mAh | 14,4 % | 11,1 % |

**Lecture.**

1. **L'ACK fait bien ce qu'on attend de lui : il multiplie les indices.** Avec des rafales et sans réponses, la part de messages qui partent avec un indice passe de 5 % à 14 % (×2,8). Avec réponses et rafales, de 31 % à 36 %. Avec des réponses seules, le gain est faible (+2 à +3 points), comme prévu au §2.1 : dans un échange alterné, chaque message porte déjà la position de son émetteur.
2. **Mais plus d'indices ne donne pas plus de livraisons à cette densité.** Aucune variante ne s'écarte de TIDE-G de plus que le bruit entre graines (±1 à 2 points). TIDE-G lui-même ne gagne que 1 à 2,4 points sur TIDE, pour **une énergie multipliée par 2 à 2,3** (le GPS des relais). Le goulot d'étranglement est la connectivité : environ 50 à 57 % de livraison et un p95 de 16 à 18 min montrent un réseau souvent coupé. Savoir où est le destinataire ne crée pas de chemin vers lui.
3. **Le spray réduit est rejeté.** Il perd de la livraison dans les trois scénarios (−0,4 à −1,9 point), et il entraîne avec lui le premier preset (« les quatre ajouts »). Dans un réseau clairsemé, couper les copies du départ coûte plus que ce que l'indice fait gagner.
4. **L'abandon de l'indice est gardé.** Il est neutre sur la livraison et réduit la surcharge quand il y a des réponses (−3,0 et −1,6). 20 à 30 % des messages à indice sont livrés après l'abandon : ils arrivent quand même, donc le délai de 180 s ne coupe pas de livraisons que l'indice aurait permises.
5. **La fusion d'indices ne rapporte rien** (0 à +0,4 point) : pas de quoi justifier l'entorse à la règle de vie privée.
6. **Les fixes ponctuels sont quasi gratuits** à cette densité : presque tous les nœuds sont relais et ont déjà un fix périodique frais.

**Conclusion provisoire.** TIDE-G2 (ACK + abandon + fixes facturés) fait au moins aussi bien que TIDE-G, avec plus d'indices et une surcharge un peu plus basse quand il y a des réponses. Mais ni TIDE-G ni TIDE-G2 ne justifient clairement leur coût GPS à cette densité. Les écarts inférieurs à 1 point ne sont pas significatifs sur 3 graines : il faut la campagne du §6 avant de trancher.

---

## 6. Campagne recommandée

L'objectif est de répondre à une seule question : **la couche géographique vaut-elle son coût énergétique ?** Toutes les commandes passent par `scripts/compare_algorithms.py`, avec les mêmes graines pour tous les algorithmes.

| Axe | Valeurs | Pourquoi |
|---|---|---|
| Algorithmes | `tide`, `tide_g`, `tide_g2` | Le cœur de la comparaison |
| Graines | au moins 10 | Les écarts attendus (1 à 2 points) sont de l'ordre du bruit sur 3 graines |
| Densité | 400 et 4 000 festivaliers (≈ 11 400/km², la densité de référence de TIDE-G) | En foule dense, l'élection limite les relais : moins de fixes, mais un réseau connexe où l'indice peut enfin servir |
| Trafic | réponses 0 / 0,5 × rafales 0 / 0,5 | La couverture d'indice en dépend directement |
| Échec du fix | 0 / 0,1 / 0,3 | Robustesse à un GPS dégradé en foule |
| Mobilité | `poi` | Sans pauses, l'indice périme trop vite pour servir |

```bash
for seed in $(seq 1 10); do
  python scripts/compare_algorithms.py --seed $seed --duration 1800 --num-festivaliers 4000 \
      --mobility poi --reply-probability 0.5 --followup-probability 0.5 --workers 2
done
```

Deux remarques sur le script :

- `ALGORITHMS` contient tous les algorithmes : pour cette campagne, le restreindre à `tide`, `tide_g` et `tide_g2` divise le temps par quatre ;
- la matrice lance chaque algorithme avec 0 et `--beacon-count` bornes. Seules les lignes à 0 borne sont comparables au §5. Avec `--beacon-count 0`, chaque algorithme tournerait deux fois à l'identique.

Ablations, sur la densité où TIDE-G2 se distingue le plus :

- `ack_hint`, `geo_giveup_s` et `charge_message_fixes` retirés un par un du preset ;
- `geo_giveup_s` : 120 / 180 / 300 s ;
- `ack_hint_delay_factor` : 0 / 1 / 2 (sensibilité au temps de retour de l'ACK) ;
- `gps_for_relays=False` sur TIDE-G2 : si l'ACK fournit assez d'indices, peut-on arrêter les fixes périodiques des relais et récupérer l'essentiel de l'énergie ? C'est l'ablation la plus prometteuse vu le point 2 du §5.

À relever en plus du rapport : `hint_stats` (couverture, `hinted_by_ack`, `delivered_after_giveup`, `message_fixes`) et la part des livraisons sous 2 min et sous 10 min (seuils du cahier des charges).

---

## 7. Impact sur l'appli KMM

- **Format de l'ACK** : un champ optionnel, chiffré pour l'émetteur original (ChaCha20-Poly1305), contenant la position en repère local et son horodatage, soit environ 12 octets de clair, 40 avec nonce et tag. Il est couvert par la signature de l'ACK : un relais ne peut ni le lire, ni le remplacer.
- **Réglage** : le partage de position doit couvrir les ACK (§2.1). Désactivé, l'ACK part sans position.
- **Fix ponctuel** : à l'envoi et à l'ACK, réutiliser le dernier fix s'il a moins de 60 s ; sinon demander un fix avec un délai court (5 s) et envoyer sans position en cas d'échec, sans retarder le message.
- **Abandon de l'indice** : la règle `âge du message > geo_giveup_s ⇒ ignorer l'indice` est locale à chaque nœud et ne demande aucun champ supplémentaire (`creation_time` est déjà dans l'en-tête signé).

---

## 8. Points d'attention

- **Le gain dépend du trafic.** Tout repose sur la part de messages qui ont un indice. Elle dépend des relances et des réponses, dont les taux réels en festival sont inconnus. À instrumenter dans l'appli (de façon anonyme) dès les premiers tests terrain.
- **ACK instantané dans le moteur.** La purge réseau reste instantanée ; seule la position de l'ACK est retardée. Si un jour l'ACK est simulé comme un vrai paquet, `ack_hint_delay_factor` disparaît au profit de son temps de trajet réel.
- **Coût GPS.** Les fixes ponctuels s'ajoutent aux fixes périodiques des relais. Avec `gps_for_relays=True`, la plupart des sources et destinataires ont déjà un fix frais, donc le surcoût est faible ; avec `gps_for_relays=False`, il devient le coût principal.
- **Fix d'envoi découplé de `src_position`.** Le fix facturé (§2.5) est pris au premier routage par la source, pas à la création, et c'est un tirage distinct du `gps_fix()` qui remplit `src_position`. Avec `fix_failure_probability > 0`, l'un peut échouer sans l'autre, et un message livré directement au destinataire (sans `decide`) ne paie rien. Effet négligeable sur l'énergie, à garder en tête pour les ablations d'échec de fix.
- **Échecs de fix indépendants.** Le modèle tire chaque échec indépendamment. En réalité, ils sont corrélés (une personne sous une tente échoue plusieurs fois de suite), ce qui est plus défavorable.
- **Densité.** Les résultats du §5 sont à densité modérée (≈ 1 140 personnes/km²), où le réseau est souvent coupé. Ils sont à refaire à la densité de référence de TIDE-G (≈ 11 400/km²) avant toute conclusion pour la thèse.
