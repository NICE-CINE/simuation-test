# BAND-FANOUT — Spécification

Relais à éventail borné : chaque copie est relayée au plus `fanout` fois, vers des voisins tirés au hasard dans une bande de distance (ni trop près, ni au bord de la portée), avec un plafond de sauts et une purge globale à la livraison.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/band_fanout.py` (`--routing band_fanout`), 30 tests dans `tests/test_routing_band_fanout.py` et 2 dans `tests/test_routing_select_links.py` (hook moteur `select_links`), balayage de variantes par `scripts/sweep_band_fanout.py`. Algorithme conçu pour ce simulateur, sans document d'origine : spec rédigée a posteriori à partir du code (après le correctif `d775dbc`). Fiche courte : `docs/algorithmes/band_fanout.md`.

---

## 1. Principe

Objectif : étendre la diffusion sans inonder, en évitant de relayer vers des voisins au bord de la portée, où le shadowing fait perdre des paquets.

1. **Tirage des relais à chaque tick** : chaque porteur tire `fanout` voisins dont la distance vaut 40 à 60 % de sa portée radio.
2. **Éventail borné** : un porteur relaie chaque message au plus `fanout` fois ; la copie reçue repart avec un budget neuf.
3. **Plafond de sauts** : au-delà de `max_hops` sauts, il ne reste que la livraison directe.
4. **Liaisons choisies par l'algo** : le hook `select_links` réserve les liaisons aux destinataires, puis aux relais tirés.
5. **Purge globale** : un message livré disparaît de tous les buffers au tick suivant.

---

## 2. Origine

Variante du gossip à éventail fixe (*k*-fanout gossip) : chaque nœud transmet à *k* voisins choisis au hasard plutôt qu'à tous. Le choix des relais dans une bande de distance, le budget par porteur et la purge sont propres à ce simulateur. L'idée de la bande vient du modèle radio : à 30 m de portée téléphone, la marge de liaison est d'environ 6 à 11 dB entre 12 et 18 m, et tombe vers 0 au bord, où le shadowing (σ du `RadioParams`) provoque des coupures.

---

## 3. Spécification

### 3.1 État

| État | Portée | Contenu |
|---|---|---|
| `_selected[holder]` | global, recalculé à chaque tick | relais tirés pour ce porteur à ce tick |
| `_relayed[holder][msg]` | global | nombre de relais déjà faits par ce porteur pour ce message |
| `_delivered` | global | identifiants des messages livrés (si `purge_delivered`) |
| `_nodes` | global | dictionnaire des nœuds, pour la purge |

Rien n'est stocké dans `routing_state` : une copie clonée par le backhaul des bornes repart donc avec un budget neuf au lieu d'hériter du budget épuisé de la borne source.

### 3.2 `on_tick` : purge et tirage

Pour chaque nœud actif (clé de `neighbors_by_node`) :

1. supprime de son buffer les messages de `_delivered` ;
2. oublie les compteurs `_relayed` des messages qui ne sont plus dans son buffer ;
3. s'il a des voisins, construit `pending`, la liste des messages qu'il peut encore relayer (`hops < max_hops` et `_relayed < fanout`). Si `pending` est vide, pas de tirage.

Tirage (`_select`) :

1. **Voisins utiles** : on garde les voisins pour lesquels au moins un message de `pending` n'est ni déjà détenu (ni déjà livré) ni destiné à ce voisin.
2. **Ratio** : `distance(gps_position(porteur), gps_position(voisin)) / portée radio du porteur`, avec les positions GPS bruitées.
3. Si au moins `fanout` voisins ont un ratio dans `[band[0], band[1]]`, on en tire `fanout` au hasard (RNG de graine `seed`).
4. Sinon, on prend tous ceux de la bande et on complète avec les voisins hors bande les plus proches de ses bords (écart `band[0] - ratio` ou `ratio - band[1]`).

Le tirage vaut pour **tous** les messages du porteur à ce tick : il n'y a pas de tirage par message.

### 3.3 `select_links` : qui obtient une liaison

Le moteur limite chaque émetteur à `max_concurrent_links` (6 par défaut) voisins. Le comportement par défaut (`RoutingAlgorithm.select_links`) garde les plus proches, selon la position réelle. En foule dense, la bande (12 à 18 m) serait alors presque toujours hors d'atteinte. `band_fanout` classe :

1. les destinataires des messages du buffer (la livraison directe ne passe pas par `decide`, mais il lui faut une liaison) ;
2. les relais tirés à ce tick ;
3. les autres voisins, du plus proche au plus loin.

Puis il coupe à `max_links`. À l'intérieur de chaque groupe, l'ordre reste celui de la distance réelle. Sans destinataire ni relais tiré, c'est le comportement par défaut.

### 3.4 Décision (`decide`)

Appelée par le moteur seulement pour un voisin qui n'est pas le destinataire, et si le TTL en sauts du moteur n'est pas atteint.

| Condition | Décision |
|---|---|
| message livré (`_delivered`) ou déjà détenu par le voisin | IGNORE |
| `hops >= max_hops` ou `_relayed[porteur][msg] >= fanout` | IGNORE |
| voisin absent de `_selected[porteur]` | IGNORE |
| sinon | FORWARD |

### 3.5 Effet d'un transfert (`on_forward`)

- `_relayed[porteur][msg] += 1` ; le porteur garde sa copie.
- `_relayed[voisin][msg]` est effacé : la copie reçue repart avec `fanout` relais.

Le moteur appelle `on_forward` juste après chaque transfert, avant le `decide` suivant : un porteur à qui il reste 1 relais et qui a 3 relais tirés n'en sert qu'un.

### 3.6 Livraison et purge (`on_delivered`)

Si `purge_delivered` : le message entre dans `_delivered` et quitte tout de suite le buffer du porteur qui l'a livré. Les autres copies disparaissent au `on_tick` suivant, et `decide` l'ignore entre-temps. Sans purge, les copies restent et continuent de se répliquer jusqu'à épuisement des budgets.

### 3.7 Buffer

Pas de `choose_eviction` : FIFO du moteur.

---

## 4. Paramètres

| Paramètre | Défaut | Contrainte | Rôle |
|---|---|---|---|
| `fanout` | 3 | ≥ 1 | relais par porteur et par message |
| `max_hops` | 4 | ≥ 1 | sauts maximum pour relayer (en plus du TTL moteur, 8 par défaut) |
| `band` | `(0.4, 0.6)` | `0 ≤ bas < haut` | fenêtre de distance, en fraction de la portée du porteur |
| `seed` | 0 | | RNG du tirage (`main.py` passe `--seed`) |
| `purge_delivered` | `True` | | purge globale à la livraison |

Avec les défauts, un arbre de copies issu d'une seule source compte au plus `1 + 3 + 9 + 27 + 81 = 121` porteurs (mais voir §8 : cette borne n'est pas stricte).

---

## 5. Implémentation dans le simulateur

- Hooks : `on_simulation_start` (dictionnaire des nœuds), `on_tick` (purge, nettoyage des compteurs, tirage), `select_links` (hook ajouté au moteur pour cet algo, défaut inchangé pour les autres), `decide`, `on_forward`, `on_delivered`.
- **Sans `ble_config`**, le moteur n'appelle ni `on_tick` ni `select_links` (pas de plafond de liaisons) : aucun relais n'est tiré et l'algo ne fait que de la livraison directe. `run_simulation` passe toujours un `ble_config`.
- La bande est relative à la portée **du porteur** : 12 à 18 m pour un téléphone (30 m), 24 à 36 m pour une borne (60 m).
- Les bornes sont des porteurs comme les autres : le backhaul clone le message sur toutes les bornes sans incrémenter `hops`, et chaque borne relaie avec son propre budget.

---

## 6. Ce qui est simplifié

- `_delivered` est global et instantané (instance partagée) : aucun ACK n'est transmis ni facturé. C'est optimiste, comme pour `dasfv`, `fresh_spray` ou `geo_spray_focus`.
- Les positions GPS du porteur et des voisins sont lues sans fix facturé, et sans échec de fix (`gps_position()`, pas `gps_fix()`). Un vrai téléphone devrait mesurer la distance au RSSI ou recevoir la position du voisin.
- `select_links` classe par position réelle, la bande par position bruitée : un relais tiré peut se trouver un peu hors bande en réalité.

---

## 7. Résultats

Balayage `scripts/sweep_band_fanout.py` : voir la fiche `docs/algorithmes/band_fanout.md` (tableau, archive et lecture). Ces chiffres (`archives/2026-10-09_09-47-35_sweep_band_fanout.csv`) et la comparaison `archives/2026-10-09_10-22-41_comparaison.csv` ont été mesurés **avant** le correctif `d775dbc` (liaisons réservées aux destinataires, budget par porteur, voisins inutiles écartés) : ils ne reflètent pas exactement le code actuel.

---

## 8. Points d'attention

- **La borne de 121 porteurs n'est pas stricte.**
  - Chaque borne qui reçoit une copie par le backhaul repart avec `fanout` relais et le même nombre de sauts : avec 6 bornes, l'arbre peut avoir jusqu'à 6 sous-arbres de plus.
  - Un nœud qui perd sa copie (éviction FIFO) puis la reçoit de nouveau repart avec un budget neuf.
- **Un tirage par porteur, pas par message** : un voisin tiré pour un message qu'il possède déjà peut ne servir que pour un autre message, ou pour aucun si `max_concurrent_links` ou le budget de liaison coupe.
- **Tirage refait à chaque tick** : pendant un long contact, le porteur retire des relais à chaque tick. C'est le budget `fanout`, pas le tirage, qui borne la réplication.
- **Ordre du tick** : le moteur prend son instantané des buffers et fait le backhaul avant `on_tick`. Une borne qui détient un message livré au tick précédent peut donc encore le cloner vers les autres bornes (transmissions de backhaul comptées), puis la purge l'efface partout. La contention de ce tick compte aussi les messages déjà purgés.
- **Nœuds inactifs** (churn, batterie vide) : absents de `neighbors_by_node`, ils ne sont purgés qu'à leur retour.
- **`_delivered` ne se vide jamais** : un entier par message livré, négligeable même en 3 h à 5 000 nœuds.
