# FRESH-SPRAY — Spécification

Spray binaire, réplication vers les voisins qui ont croisé le destinataire récemment, passage de la dernière copie au plus « frais », une réplique sur le réseau de bornes, et purge globale à la livraison.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/fresh_spray.py` (`--routing fresh_spray`), 7 tests dans `tests/test_routing_fresh_spray.py`, balayage de `initial_tokens` par `scripts/sweep_fresh_spray_tokens.py`. Algorithme conçu pour ce simulateur, sans document d'origine : spec rédigée a posteriori à partir du code. Résultats et fiche courte : `docs/algorithmes/fresh_spray.md`.

---

## 1. Principe

Objectif : maximiser la livraison tout en limitant latence et énergie.

1. **Spray binaire** : le message naît avec `initial_tokens` jetons, partagés moitié-moitié.
2. **Rencontre récente** : un voisin qui a croisé le destinataire depuis moins de `met_dst_window_s` reçoit une copie, même quand le porteur n'a plus de jetons à donner.
3. **Focus FRESH** : la dernière copie passe au voisin qui a vu le destinataire plus récemment que le porteur ; le porteur la supprime.
4. **Bornes** : une seule réplique vers le réseau de bornes, que le backhaul diffuse ensuite à toutes.
5. **Purge globale** : dès la livraison, toutes les copies sont supprimées.
6. **Batterie** : un voisin sous 15 % ne reçoit pas de relais.

---

## 2. Origine

Combinaison de trois idées de la littérature :

- Spray and Wait binaire (Spyropoulos et al., 2005) pour le budget de copies ;
- FRESH (H. Dubois-Ferrière, M. Grossglauser, M. Vetterli, *Age Matters: Efficient Route Discovery in Mobile Ad Hoc Networks Using Encounter Ages*, MobiHoc 2003) pour le passage au nœud qui a vu la destination le plus récemment ;
- Spray and Focus (Spyropoulos et al., 2007) pour la phase de focus.

La réplication vers les voisins « qui ont vu la destination », la réplique unique sur les bornes et la purge sont propres à ce simulateur.

---

## 3. Spécification

### 3.1 État

| État | Portée | Contenu |
|---|---|---|
| `last_seen[a][b]` | global | dernier tick où `a` et `b` étaient à portée (toutes les paires, via `on_tick`) |
| `delivered` | global | `msg_id` déjà livrés |
| `routing_state["tokens"]` | par copie | jetons ; absent = `initial_tokens` |
| `routing_state["on_beacon"]` | par copie | cette lignée a déjà été donnée à une borne |

### 3.2 Décision

Pour chaque message `m` (destinataire `d`) du porteur `A`, à chaque contact avec `B` :

```
si m est livré                                  → retirer m de A ; IGNORE
si B détient m ou l'a déjà reçu                 → IGNORE
si B est une borne :
    si m.on_beacon                              → IGNORE
    sinon                                       → FORWARD (raison « beacon »)
si batterie(B) < battery_low_pct                → IGNORE
si t − last_seen[B][d] ≤ met_dst_window_s       → FORWARD (raison « met_dst »)
si tokens(m) > 1                                → FORWARD (raison « spray »)
si last_seen[B][d] > last_seen[A][d] + min_gain → FORWARD (raison « focus »)
sinon                                           → IGNORE
```

`last_seen` vaut −∞ pour une paire jamais vue.

### 3.3 Effet d'un transfert (`on_forward`)

| Raison | Copie de A | Copie de B |
|---|---|---|
| `beacon` | marquée `on_beacon`, jetons inchangés | marquée `on_beacon`, 1 jeton |
| `met_dst` | inchangée | 1 jeton |
| `spray` | `n − floor(n/2)` jetons | `floor(n/2)` jetons |
| `focus` | supprimée (sauf si A est une borne, qui la garde) | 1 jeton |

### 3.4 Purge

- À la livraison : `msg_id` entre dans `delivered`, et le porteur qui a livré retire sa copie.
- À chaque tick : tout nœud retire de son buffer les messages livrés.
- Dans `decide` : une copie livrée encore présente est retirée.

### 3.5 Buffer

FIFO du moteur (pas de `choose_eviction`).

---

## 4. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `initial_tokens` | 16 | budget de spray ; vérifié à 5 000 festivaliers (4 / 8 / 16 / 32) |
| `met_dst_window_s` | 1 200 s | âge maximal d'une rencontre avec le destinataire pour mériter une copie |
| `min_freshness_gain_s` | 5 s | gain de fraîcheur minimal pour le focus |
| `battery_low_pct` | 0,15 | sous ce niveau, un voisin ne reçoit plus de relais |

---

## 5. Implémentation dans le simulateur

- Hooks : `on_simulation_start` (dictionnaire des nœuds pour la purge), `on_tick` (table `last_seen` et purge), `decide`, `on_forward`, `on_delivered`.
- `on_tick` voit toutes les paires à portée, même sans message à échanger : la table de rencontres n'est pas sous-échantillonnée comme dans `prophet`.
- Les bornes sont reconnues par `is_beacon`. Le backhaul copie `routing_state`, donc toutes les bornes héritent de `on_beacon` et ne redonnent pas le message à une autre borne.
- **Pourquoi la purge compte pour l'énergie** : le moteur facture une émission pour chaque tentative perdue, sur chaque message en buffer. Moins de copies périmées, c'est moins d'énergie perdue en pertes et moins de contention.

---

## 6. Ce qui est simplifié

- `last_seen` et `delivered` sont globaux et instantanés (instance partagée) : dans une appli, il faudrait échanger les âges de rencontre au contact et propager des ACK. C'est optimiste, comme pour `dasfv`.
- La batterie du voisin est lue directement, sans annonce.
- La réplique « unique » vers les bornes l'est par lignée de copies : deux lignées qui croisent chacune une borne avant que le backhaul ne les ait servies peuvent en déposer deux. Sans effet pratique, le backhaul étant quasi instantané.

---

## 7. Résultats

Voir `docs/algorithmes/fresh_spray.md` :

- 500 festivaliers, 1 h, graine 42 : 72,3 % de livraison sans bornes et 81,7 % avec 6 bornes, la meilleure de la comparaison, pour moins d'énergie que `dasfv`, `gossip_a` et `epidemic`.
- 5 000 festivaliers, 3 h, mobilité `poi`, 6 bornes, graines 1 à 3 : la livraison plafonne vers 82 % quel que soit `initial_tokens`. Chaque doublement gagne environ 4 % de latence pour 5 à 12 % d'énergie en plus.

---

## 8. Points d'attention

- **TTL en sauts** : environ 8,5 sauts en moyenne pour un TTL moteur de 8 : le TTL bride probablement la réplication `met_dst`.
- **Buffers pleins** : environ 10 millions d'évictions FIFO dans le balayage à 5 000 nœuds. Une politique `choose_eviction` (supprimer d'abord les copies à 1 jeton sans rencontre récente) est la piste la plus directe.
- **`met_dst_window_s`** n'est calibré que sur un scénario (500 nœuds, `random_waypoint`).
- **Coût de la purge** : elle parcourt tous les buffers à chaque tick dès qu'un message est livré, ce qui ralentit la simulation, pas le réseau simulé.
