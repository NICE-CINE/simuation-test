# Spray and Wait — Spécification

Spray and Wait binaire : un budget fixe de copies, réparti moitié-moitié, puis attente du destinataire.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/spray_and_wait.py` (`--routing spray_wait`), 7 tests dans `tests/test_routing_spray_and_wait.py`. Spec rédigée a posteriori à partir du code : elle décrit l'implémentation, pas un document d'origine. Fiche courte : `docs/algorithmes/spray_wait.md`.

---

## 1. Principe

1. **Spray** : un message naît avec `L` jetons. Tant qu'une copie porte plus d'un jeton, elle en donne la moitié à chaque voisin qui ne l'a pas.
2. **Wait** : une copie à un seul jeton n'est plus transmise qu'au destinataire lui-même.

Le nombre total de copies est donc borné par `L`.

---

## 2. Référence

T. Spyropoulos, K. Psounis, C. S. Raghavendra, *Spray and Wait: An Efficient Routing Scheme for Intermittently Connected Mobile Networks*, ACM SIGCOMM WDTN, 2005. Variante « binaire » de l'article.

---

## 3. Spécification

### 3.1 État par copie

`routing_state["copies_left"]` : jetons portés par cette copie. Absent à la création, il vaut alors `L`.

### 3.2 Décision

Pour chaque message `m` du porteur `A`, à chaque contact avec `B` :

```
si B détient m ou l'a déjà reçu   → IGNORE
si copies_left(m) ≤ 1             → IGNORE   (phase wait)
sinon                             → FORWARD
```

### 3.3 Partage des jetons (`on_forward`)

```
n = copies_left(m)
A garde  floor(n / 2)
B reçoit n − floor(n / 2)
```

Exemple avec `L = 8` : 8 → 4 + 4 → 2 + 2 → 1 + 1. Chaque copie finit à 1 jeton, au plus 8 copies au total.

### 3.4 Buffer et livraison

FIFO du moteur, aucune purge après livraison.

---

## 4. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `initial_copies` (`L`) | 8 | budget de copies ; doit être ≥ 2. Option `--spray-initial-copies` dans `main.py` |

`scripts/compare_algorithms.py` instancie l'algorithme sans argument, donc toujours avec `L = 8`.

---

## 5. Implémentation dans le simulateur

- Hooks : `decide` et `on_forward`.
- La phase wait repose sur le moteur : la livraison directe au destinataire est faite sans appeler `decide`, donc une copie à 1 jeton reste livrable.
- Le TTL en sauts du moteur (8) ne bloque jamais le spray en pratique : avec `L = 8`, une copie a au plus 3 sauts de spray.

---

## 6. Écarts avec la référence

| Article | Simulateur |
|---|---|
| Le porteur garde `ceil(n/2)`, le voisin reçoit `floor(n/2)` | Inversé : le porteur garde `floor(n/2)`, le voisin reçoit `ceil(n/2)`. Identique pour `n` pair, donc pour `L = 8` |
| `L` choisi selon la taille du réseau et le délai visé | `L` fixe, indépendant de la densité |

---

## 7. Points d'attention

- **Aveugle** : les copies vont au premier venu, sans critère de rencontre avec le destinataire.
- **Latence de la phase wait** : une fois les jetons distribués, la livraison ne dépend plus que de la mobilité.
- **`L` fixe** : trop peu de copies en zone clairsemée, trop en zone dense. `dasfv`, `tide` et `geo_spray_focus` adaptent ce budget.
- **Aucune purge** : les copies livrées restent en buffer jusqu'à expiration.
- **Énergie** : l'algorithme le plus économe de la comparaison à 500 festivaliers (560 555 mAh), pour 41,9 % de livraison (`docs/algorithmes/fresh_spray.md`).
