# HORIZON — Spécification

`fresh_spray` complété par un champ de distances en sauts (vecteurs de distance bornés à `horizon_hops`) le long duquel une copie proche de son destinataire est tirée, un saut par tick.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/horizon.py` (`--routing horizon`), 7 tests dans `tests/test_routing_horizon.py` (hooks moteur testés dans `tests/test_network.py`). Algorithme conçu pour ce simulateur, sans document d'origine : spec rédigée à partir du code. Fiche courte : `docs/algorithmes/horizon.md`.

---

## 1. Motivation

Mesure sur `fresh_spray` (500 festivaliers, mobilité `poi`, 6 bornes, réponses à 0,5, seeds 1 et 2), distance en sauts source → destinataire dans le graphe de voisinage au moment de la première décision :

| Situation à la création | Part | Livrés | Latence médiane |
|---|---|---|---|
| destinataire à 8 sauts ou moins | 31–32 % | 96–99 % | 32–41 s |
| même composante, plus de 8 sauts | ~28 % | 92–94 % | 280–292 s |
| autre composante | ~40 % | 91–93 % | 263–314 s |

La foule forme une composante géante (60 % des destinataires y sont reliés à la source) dont les chemins font jusqu'à 20 sauts et plus. Même à 8 sauts ou moins, la livraison prend une demi-minute au lieu de quelques secondes. Aucun algorithme existant n'exploite cette topologie comme un gradient : les îlots de `tide` et de `geo_spray_focus` ont un rayon d'un saut, `bitchat` n'en tire qu'un booléen « joignable » qui déclenche une inondation.

---

## 2. Origine

Hybride MANET/DTN dans l'esprit de HYMAD (J. Whitbeck, V. Conan, *HYMAD: Hybrid DTN-MANET routing for dense and highly dynamic wireless networks*, Computer Communications 33(13), 2010) : routage par table à l'intérieur des groupes connexes, stockage-transport entre eux. Le champ de distances est un DSDV réduit (C. Perkins, P. Bhagwat, SIGCOMM 1994) sans numéros de séquence, remplacé par une reconstruction complète à chaque tour. La phase DTN est `fresh_spray` (voir `FRESH-SPRAY.md`).

---

## 3. Champ de distances

- Chaque nœud annonce une fois par `announce_period_s` (défaut 5 s), à sa propre phase (`id × 0,618… mod 1` de la période) : la foule n'annonce jamais dans le même tick.
- Juste avant d'annoncer, `u` reconstruit son vecteur à partir du dernier vecteur entendu de chaque voisin depuis moins de `entry_ttl_s` (défaut 15 s, trois périodes) :
  `dist_u(d) = min sur ces voisins v de dist_v(d) + 1`, gardé seulement si `≤ horizon_hops`, et `dist_u(u) = 0`. Il diffuse ce vecteur, qu'il utilise aussi pour router jusqu'à sa prochaine annonce.
- Rétention : une annonce perdue n'efface pas la route ; un voisin muet depuis plus de `entry_ttl_s` disparaît. Pas de comptage à l'infini au-delà de l'horizon.
- Pourquoi la rétention : une première version reconstruisait le vecteur uniquement à partir des annonces du tour. Or une annonce n'atteint un voisin donné qu'une fois sur trois environ (mesuré en `poi`, 500 festivaliers : degré moyen 13, vecteurs de 525 octets, 32 % d'annonces non émises par backoff, 42 % des autres perdues), et une route à k sauts exigeait k réceptions consécutives : le champ s'effondrait. Avec rétention et phases étalées, les tirages doublent.
- Radio : les vecteurs passent par le moteur (`control_broadcasts` / `on_control_received` de `RoutingAlgorithm`, `network._send_control_broadcast`). Chaque nœud diffuse `n × announce_entry_bytes` octets (`n` = entrées de son vecteur, au plus `max_announce_bytes / announce_entry_bytes` : au-delà, seules les destinations les plus proches sont annoncées, le moteur n'enverrait jamais un vecteur plus gros que le budget d'antenne d'un tick) à son tour dans l'ordre aléatoire du tick, juste avant ses données, avec les mêmes règles qu'un message : backoff CSMA, budget d'antenne partagé (émetteur et chaque récepteur), terme de congestion des liens (plafonnés à `max_concurrent_links`), perte par récepteur (marge de liaison, shadowing, collisions), énergie tx/rx du run (énergie mesh). Seule différence : pas de créneau de liaison (diffusion sans connexion). L'algorithme ne fusionne que les vecteurs effectivement reçus ; `on_control_received` arrive une fois par tick, après toutes les données.
- `stats` : `pull`, `announces_sent`, `announces_received`, `announce_bytes`, `announce_rx_bytes`.
- Les bornes participent comme les téléphones (énergie gratuite) ; le backhaul ne propage pas les vecteurs.

---

## 4. Décision

Pour un message `m` (destinataire `d`) porté par `A`, au contact de `B` :

1. `m` déjà livré, ou `B` a déjà `m` : comportement `fresh_spray` (purge ou IGNORE).
2. **Tirage.** Prochain saut de `A` vers `d` : le voisin `v` du tick qui minimise `(dist_v(d), distance physique A–v)`, parmi ceux tels que `dist_v(d) < dist_A(d)` (`horizon_hops + 1` si `A` n'a pas d'entrée). `dist_v(d)` est lu dans le dernier vecteur que `A` a reçu de `v` depuis moins de `entry_ttl_s`, jamais dans la table courante de `v` : une annonce perdue l'est aussi pour le routage. S'il existe et que `hops(m) + dist_v(d) ≤ ttl_hops` (il reste `dist_v(d) − 1` relais, puis une livraison directe que le TTL ne bloque pas) :
   - `B = v` : FORWARD, raison `pull` ;
   - sinon : IGNORE (la copie attend son prochain saut).
3. **Réserve.** Si `ttl_hops` est défini et `hops(m) ≥ ttl_hops − horizon_hops` : IGNORE.
4. Sinon : décision `fresh_spray`.

À la réception d'un tirage (`on_forward`) : la copie reçue prend les jetons du porteur, le porteur supprime la sienne (sauf une borne, qui la garde comme dans `fresh_spray`), `stats["pull"]` est incrémenté. Un tirage perdu (perte de paquet, budget d'antenne) n'appelle pas `on_forward` : le porteur garde la copie et retente.

Les prochains sauts sont mis en cache par `(porteur, destinataire)` pour le tick.

---

## 5. Liaisons

`select_links` place en tête les prochains sauts de tirage des messages du porteur (dont le destinataire lui-même s'il est voisin, à distance 0), puis les voisins les plus proches, dans la limite de `max_concurrent_links`. Sans message à tirer, ordre par défaut.

---

## 6. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `horizon_hops` | 5 | Rayon du champ et taille de la réserve de sauts |
| `announce_period_s` | 5,0 | Période des annonces de chaque nœud |
| `entry_ttl_s` | 15,0 | Rétention du dernier vecteur entendu d'un voisin |
| `announce_entry_bytes` | 5 | Taille d'une entrée (id 4 o + distance 1 o) |
| `max_announce_bytes` | 1650 | Taille max d'une annonce (données max d'un advertising étendu BLE 5) |
| `**fresh_spray_kwargs` | ceux de `fresh_spray` | Phase DTN |

---

## 7. Non modélisé

Numéros de séquence DSDV, canaux d'advertising séparés (l'annonce partage le budget d'antenne des données), asymétrie de liens (on lit la liste de voisins du moteur dans un seul sens), vie privée (les identifiants sont annoncés en clair sur H sauts).

---

## 8. Résultats

`scripts/compare_algorithms.py --algorithms fresh_spray horizon --seeds 1 2 3 --duration 3600 --num-festivaliers 500 --beacon-count 6 --mobility poi --reply-probability 0.5` (moyennes sur 3 seeds, annonces passées par la radio) :

| | Livraison | Latence | p95 | Sauts | Overhead | Énergie mesh | Paquets perdus |
|---|---|---|---|---|---|---|---|
| `fresh_spray`, 6 bornes | 0,996 | 298 s | 948 s | 7,01 | 59,6 | 23,27 Ah | 50 409 |
| `horizon`, 6 bornes | 0,990 | 245 s | 875 s | 5,81 | 26,2 | 23,48 Ah | 27 417 |
| `fresh_spray`, sans borne | 0,980 | 462 s | 1 287 s | 7,00 | 61,7 | 23,27 Ah | 49 907 |
| `horizon`, sans borne | 0,984 | 379 s | 1 185 s | 6,67 | 29,9 | 23,47 Ah | 30 135 |

Latence −18 % (plus basse sur chacune des 6 paires de seeds), overhead −56 %, énergie mesh +0,9 % (les annonces), livraison −0,6 pt avec bornes, +0,4 pt sans. Avec des annonces gratuites et sans perte (première version), la latence tombait à 209 s : la radio coûte environ 35 s de latence et 1 point de livraison.
