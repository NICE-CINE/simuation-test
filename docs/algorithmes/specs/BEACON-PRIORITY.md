# Beacon Priority — Spécification

Inondation entre téléphones, arrêtée dès qu'une copie atteint une borne : le réseau filaire des bornes prend alors le relais.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/beacon_priority.py` (`--routing beacon_priority`), 6 tests dans `tests/test_routing_beacon_priority.py`. Algorithme conçu pour ce simulateur, sans document d'origine : spec rédigée a posteriori à partir du code. Fiche courte : `docs/algorithmes/beacon_priority.md`.

---

## 1. Principe

1. Tant qu'un message n'a pas vu de borne, il se propage comme dans `epidemic`.
2. Toute borne croisée reçoit une copie. Cette copie et celle du porteur sont marquées `reached_beacon`.
3. Une copie marquée n'est plus donnée à aucun téléphone. Le backhaul la diffuse à toutes les bornes, qui la livrent au destinataire quand il passe à portée.

Sans borne, l'algorithme est exactement `epidemic`.

---

## 2. Origine

Baseline « infrastructure d'abord » écrite pour mesurer ce que les bornes apportent à elles seules. Elle n'a pas de référence dans la littérature.

---

## 3. Spécification

### 3.1 État par copie

`routing_state["reached_beacon"]` : vrai si cette copie ou l'une de ses ancêtres a été donnée à une borne.

### 3.2 Décision

Pour chaque message `m` du porteur `A` (téléphone ou borne), à chaque contact avec `B` :

```
si B détient m ou l'a déjà reçu   → IGNORE
si B est une borne                → marquer m (copie de A) ; FORWARD
si m est marqué                   → IGNORE
sinon                             → FORWARD
```

Le marquage est posé sur la copie de `A` avant que le moteur ne crée celle de `B`. Les deux en héritent, ainsi que les copies diffusées ensuite par le backhaul.

### 3.3 Conséquences

- Une borne ne donne jamais un message à un téléphone qui n'est pas le destinataire : sa copie est marquée.
- Seule la lignée de copies qui a touché une borne s'arrête. Les copies créées avant, ou dans une autre branche, continuent d'inonder.
- La livraison par une borne passe par la branche de livraison directe du moteur, qui ne consulte pas `decide`.

### 3.4 Buffer et livraison

FIFO du moteur, aucune purge après livraison.

---

## 4. Paramètres

Aucun paramètre propre. Le comportement dépend du nombre et du placement des bornes et du backhaul :

| Réglage moteur | Défaut | Effet |
|---|---|---|
| `--beacon-count` / `BeaconConfig` | selon le scénario | 0 borne = `epidemic` |
| `BeaconConfig.backhaul_latency_s` | 0,05 s | probabilité de tentative par tick entre bornes |
| `BeaconConfig.backhaul_loss_probability` | 0 | perte sur le backhaul (réessai au tick suivant) |

---

## 5. Implémentation dans le simulateur

- Seul `decide` est implémenté. La borne est reconnue par l'attribut `is_beacon` (duck typing, sans import de `nodes.py`).
- Le backhaul (`network.beacon_backhaul_relay`) copie le message, `routing_state` compris, d'une borne à toutes les autres, sans portée radio, sans TTL en sauts et sans incrémenter `hops`.
- Les bornes ont une batterie illimitée (`battery_mah = inf`) : leur consommation est exclue de la moyenne d'énergie du rapport.

---

## 6. Points d'attention

- **Overhead proche d'`epidemic`** : le marquage ne coupe que les copies qui ont vu une borne.
- **Dépendance aux bornes** : livraison et overhead varient fortement avec leur nombre et leur placement (grille par défaut).
- **Backhaul optimiste** : par défaut, il est quasi instantané et sans perte.
- **Aucune purge** après livraison.
