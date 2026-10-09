# PRoPHET — Spécification

Routage probabiliste par historique de rencontres : une copie n'avance que vers un nœud qui a plus de chances de croiser le destinataire.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/prophet.py` (`--routing prophet`), 7 tests dans `tests/test_routing_prophet.py`. Spec rédigée a posteriori à partir du code : elle décrit l'implémentation, pas un document d'origine. Fiche courte : `docs/algorithmes/prophet.md`.

---

## 1. Principe

Chaque paire de nœuds a une *prédictabilité de rencontre* `P(a, b)` ∈ [0, 1]. Elle augmente quand `a` et `b` se croisent et décroît avec le temps. Le porteur réplique un message vers un voisin dont la prédictabilité vers le destinataire est meilleure que la sienne.

---

## 2. Référence

A. Lindgren, A. Doria, O. Schelén, *Probabilistic Routing in Intermittently Connected Networks*, ACM SIGMOBILE MC2R, 2003. Standardisé plus tard dans la RFC 6693 (2012).

---

## 3. Spécification

### 3.1 État (global, partagé)

- `P[(a, b)]` : prédictabilité de `a` vers `b`, absente = 0.
- `last[(a, b)]` : instant de la dernière mise à jour de `P[(a, b)]`.

Les deux tables sont orientées, mais une rencontre met toujours à jour les deux sens.

### 3.2 Vieillissement

Calculé à la lecture, sans tâche périodique :

```
P_vieilli(a, b, t) = P[(a, b)] · γ^(t − last[(a, b)])        (t en secondes)
```

### 3.3 Rencontre

À chaque tick, pour chaque nœud `A` et chacun de ses voisins `B`, qu'ils aient ou non des messages à échanger. Un contact qui dure plusieurs ticks ne compte qu'une fois : il y a rencontre seulement si `B` n'était pas voisin de `A` au tick précédent.

```
si (A, B) n'était pas en contact au tick précédent :
    p = P_vieilli(A, B, t)
    P[(A, B)] ← p + (1 − p) · P_INIT
    last[(A, B)] ← t
```

Chaque nœud met à jour sa propre table : `P[(B, A)]` est mis à jour quand le moteur traite la liste de voisins de `B`. Pour deux téléphones, les deux sens sont donc mis à jour au même tick.

### 3.4 Transitivité (désactivée par défaut)

Après une rencontre de `A` avec `B`, pour chaque `C` connu de `B` (`B` fait de même avec la table de `A` lors de sa propre rencontre) :

```
P[(A, C)] ← p + (1 − p) · P(A, B) · P(B, C) · β        avec p = P_vieilli(A, C, t)
```

### 3.5 Décision

Pour chaque message `m` (destinataire `d`) du porteur `A`, à chaque contact avec `B` :

```
si B détient m ou l'a déjà reçu          → IGNORE
si P(B, d) − P(A, d) > seuil             → FORWARD (A garde sa copie)
sinon                                    → IGNORE
```

### 3.6 Buffer et livraison

FIFO du moteur, aucune purge après livraison.

---

## 4. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `p_encounter_init` (`P_INIT`) | 0,75 | renforcement à chaque rencontre |
| `gamma` (`γ`) | 0,999 par seconde (≈ 0,970 par 30 s) | vieillissement |
| `beta` (`β`) | 0,25 | poids de la transitivité |
| `forwarding_threshold` | 0,0 | écart minimal de prédictabilité pour transmettre |
| `enable_transitivity` | `False` | la transitivité parcourt toute la table : trop coûteuse à grande échelle |

---

## 5. Implémentation dans le simulateur

- Une seule instance pour toute la simulation : les tables sont globales, pas portées par chaque nœud ni échangées sur BLE.
- Hooks : `on_tick` enregistre les rencontres (toutes les paires à portée, comme `tide` et `fresh_spray`) ; `decide` ne fait que comparer les prédictabilités.
- Pas de hook `on_forward` : le porteur garde toujours sa copie, PRoPHET réplique, il ne déplace pas.

---

## 6. Écarts avec la référence

| Article / RFC 6693 | Simulateur |
|---|---|
| Vieillissement par unité de temps choisie (`γ` = 0,98) | `γ` = 0,999 par seconde |
| Vecteurs de prédictabilité échangés au contact | Table globale lue directement |
| Stratégies de transfert (GRTR, GTMX…) et de file d'attente | Règle GRTR simple (`P(B,d) > P(A,d)`), file FIFO |

---

## 7. Points d'attention

- **Correction du 9 octobre 2026** : avant, les rencontres n'étaient enregistrées que dans `decide`, donc seulement quand `A` avait un message à offrir à `B`, et une fois **par tick** pendant un contact long. PRoPHET apprenait trop lentement. Sur 500 festivaliers, 1 800 s, graine 42 : livraison 22,5 % → 30,3 % en `random_waypoint` et 25,2 % → 45,8 % en `poi`. L'overhead et l'énergie augmentent (×1,4 à ×2,1) : plus de nœuds ont une prédictabilité utile, donc plus de copies. **Les comparaisons archivées avant cette date sous-estiment PRoPHET.**
- **Aucune borne sur le nombre de copies** : un gradient bruité peut répliquer beaucoup.
- **Mobilité** : avec `random_waypoint`, les rencontres se répètent peu et `P` porte peu d'information ; la mobilité `poi` lui est plus favorable.
- **Aucune purge** après livraison.
