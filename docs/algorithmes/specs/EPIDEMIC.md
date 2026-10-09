# Epidemic — Spécification

Routage épidémique : inondation par stockage-transport, référence haute d'overhead pour les autres algorithmes.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/epidemic.py` (`--routing epidemic`, algorithme par défaut de `main.py`), 2 tests dans `tests/test_routing.py`. Spec rédigée a posteriori à partir du code : elle décrit l'implémentation, pas un document d'origine. Fiche courte : `docs/algorithmes/epidemic.md`.

---

## 1. Principe

À chaque contact, le porteur donne au voisin une copie de chaque message que ce dernier n'a pas. Le porteur garde sa propre copie. Chaque message finit donc copié chez presque tous les nœuds qu'il peut atteindre avant d'expirer.

---

## 2. Référence

A. Vahdat, D. Becker, *Epidemic Routing for Partially-Connected Ad Hoc Networks*, rapport technique CS-2000-06, Duke University, 2000.

Dans l'article, deux nœuds qui se rencontrent échangent leurs *summary vectors* (ensemble des identifiants de messages détenus), puis chacun demande les messages qui lui manquent. Un compteur de sauts et une taille de buffer bornent la diffusion.

---

## 3. Spécification

### 3.1 État

Aucun. L'algorithme ne garde rien entre deux décisions.

### 3.2 Décision

Pour chaque message `m` du porteur `A`, à chaque contact avec `B` :

```
si B détient m (buffer) ou l'a déjà reçu comme destinataire → IGNORE
sinon                                                     → FORWARD (A garde sa copie)
```

### 3.3 Buffer

Pas de politique propre : quand une copie arrive dans un buffer plein, le moteur évince le message le plus ancien (FIFO, `BaseNode.store_message`).

### 3.4 Après livraison

Rien. Les copies restent dans les buffers jusqu'à leur expiration (`message_ttl_s`) ou leur éviction. Le moteur empêche seulement de relivrer un message à sa destination.

---

## 4. Paramètres

Aucun paramètre propre. Le comportement dépend uniquement des réglages du moteur :

| Réglage moteur | Défaut | Effet |
|---|---|---|
| `TrafficConfig.message_ttl_s` | 1 800 s | durée de vie d'une copie |
| `TrafficConfig.message_ttl_hops` | 8 | au-delà, plus de relais (la livraison directe reste possible) |
| `SimulationConfig.node_buffer_capacity` | 100 | taille du buffer, éviction FIFO |

---

## 5. Implémentation dans le simulateur

- Seul `decide` est implémenté ; aucun hook (`on_tick`, `on_forward`, `on_delivered`, `choose_eviction`).
- La livraison directe (voisin = destinataire) est faite par le moteur sans appeler `decide`, comme pour tous les algorithmes.
- `contact.has_message` couvre le buffer **et** les messages déjà livrés au voisin : c'est l'équivalent du *summary vector*, lu directement dans l'état du nœud.

---

## 6. Écarts avec la référence

| Article | Simulateur |
|---|---|
| Échange de *summary vectors* avant transfert | Lecture directe du buffer du voisin, sans coût d'échange |
| Compteur de sauts propre à l'algorithme | TTL en sauts du moteur (`message_ttl_hops`), commun à tous les algorithmes |
| Choix de la politique de buffer | FIFO du moteur |
| Les deux nœuds échangent dans les deux sens | Idem : le moteur traite chaque nœud comme émetteur à chaque tick |

---

## 7. Points d'attention

- **Saturation auto-infligée** : en foule dense, les évictions FIFO et les pertes par contention font chuter la livraison. À 500 festivaliers sur 1 h, `epidemic` livre 25,9 % contre 72,3 % pour `fresh_spray` (`docs/algorithmes/fresh_spray.md`).
- **Aucune purge** : un message livré continue de circuler et de consommer de l'énergie jusqu'à son expiration.
- **Référence, pas candidat** : il sert à mesurer ce que les autres algorithmes économisent, pas à être déployé.
