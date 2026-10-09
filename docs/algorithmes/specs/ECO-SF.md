# ECO-SF — Energy-Constrained Opportunistic Spray & Focus

Algorithme de routage DTN unicast pour NICE, sans GPS, qui cherche à maximiser le taux de livraison tout en minimisant les réveils radio et les connexions.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/eco_sf.py` (`--routing eco_sf`), 11 tests dans `tests/test_routing_eco_sf.py`. Conception non validée : toutes les valeurs numériques sont des points de départ.

---

## 0. Réduction simulateur

Comme DASF-V ou TIDE, ECO-SF est réduit au niveau réseau : une seule instance observe tous les nœuds, sans simuler les trames.

**Modélisé**

| Spec | Simulateur |
|---|---|
| Beacons Trickle (§4.1) | Timer Trickle par nœud dans `on_tick`. Un beacon émis est entendu par tous les nœuds actifs à portée ce tick-là. Reset : nouveau voisin, `digestEpoch` d'un voisin changé, message créé ou reçu (sauf message tardif), purge par ACK. Comme dans la RFC 6206, un reset ne fait rien si l'intervalle vaut déjà `Imin`. |
| Découverte | Une paire ne peut ouvrir de connexion que si l'un des deux a entendu un beacon de l'autre, et que l'entrée n'a pas expiré (`3 × Imax` de l'émetteur). La livraison directe au destinataire reste gérée par le moteur, sans passer par cette condition (comme pour tous les algos). |
| Utilité (§4.2) | PRoPHET allégé : renforcement `ALPHA` sur un *nouveau* voisin entendu, vieillissement `GAMMA` par minute, table de 64 entrées (éviction de l'utilité la plus faible), transitivité sur les 32 meilleures entrées, appliquée seulement à l'ouverture d'une connexion. |
| Budget de copies (§4.3) | `ceil(L0·sqrt(N_REF / n̂))` borné à [2, L_MAX], fixé à la création. `n̂` = voisins entendus sur les 60 dernières secondes. |
| Décision de connexion (§4.4) | Batterie du pair < 10 % : refus. Sinon, connexion si le porteur a un message pour le pair, ou un message non tardif que le pair n'a pas et pour lequel son utilité dépasse `dest_bloom_threshold` (0,05 : la spec ne fixe pas ce seuil). Cooldown de 20 s par paire. Une connexion dure un tick et sert aux deux sens. |
| Échange (§4.5) | Spray pondéré `w ∈ [0,25 ; 0,75]`, focus avec hystérésis `DELTA`. L'utilité du pair est lue dans le top 32 échangé. |
| Délais (§4.7) | Au-delà de 10 min, le message n'est plus relayé (livraison directe seulement) et n'a plus le droit de réinitialiser le timer Trickle. Le TTL reste celui de `TrafficConfig`. |
| Batterie (§4.8) | `Imax` = 30 / 60 / 120 s. Sous 20 % : refuse les relais. Sous 10 % : muet, sauf s'il porte un message dont il est la source. |
| Buffer (§4.6) | `choose_eviction` : on supprime d'abord les messages acquittés ou expirés, puis le message de plus faible priorité ; un message propre n'est évincé que s'il n'y a plus de message tiers. |

**Omis**

- Bloom filters, lus comme des ensembles exacts : pas de faux positifs, donc pas de connexions inutiles.
- ACK signés : remplacés par une purge globale instantanée (comme les autres algos).
- Ordre de transfert par priorité : c'est le moteur qui fixe l'ordre.
- Lissage EWMA de `n̂`.
- Plafond anti-spam des resets (pas d'attaquant simulé).
- `BUFFER_MAX` : la capacité du buffer vient de `node_buffer_capacity`.
- **Coût énergétique des beacons** : le moteur facture un courant de fond fixe (`background_current_ma`) quel que soit l'algorithme, donc Trickle n'économise rien dans le rapport. `stats` donne le proxy énergie de la spec (§9) : `beacons`, `trickle_resets`, `connections`, `spray`, `focus`.

## 0.1 Premiers résultats (non concluants : 1 graine, 30 min)

Configuration : `--mobility poi --beacons 6 --num-festivaliers 1000 --duration 1800 --seed 42`.

| Algo / variante | Livraison | Latence moy. | Overhead | Énergie (mAh) | Connexions |
|---|---|---|---|---|---|
| `fresh_spray` | 78,9 % | 241 s | 92 | 6179 | — |
| `dasfv` | 33,0 % | 383 s | 101 | 3453 | — |
| **`eco_sf`** | **12,4 %** | 530 s | 24 | 1203 | 12 577 |
| sans filtre de connexion (`dest_bloom_threshold=-1`) | 20,7 % | 566 s | 34 | 1518 | 225 818 |
| sans règle « tardif » (`late_after_s=1e9`) | 15,0 % | 592 s | 35 | 1360 | 24 143 |
| Trickle rapide (`i_max_s=2`) | 9,1 % | 598 s | 13 | 1079 | 1 482 |
| sans suppression Trickle (`trickle_k=10**6`) | 12,9 % | 502 s | 17 | 1152 | 13 161 |
| les trois relâchés + sans suppression | 19,1 % | 481 s | 28 | 1386 | 280 870 |

Ce qu'on en retient :

1. **La suppression Trickle cache des voisins.** Avec `k = 1`, un nœud qui entend un beacon cohérent se tait pendant tout l'intervalle. Les nouveaux arrivants ne le découvrent donc pas. Avec un Trickle rapide, la suppression joue à chaque intervalle et le nombre de connexions est divisé par 8. Trickle sert à faire converger un état partagé ; ce n'est pas un mécanisme de découverte de voisins.
2. **Le filtre de connexion (`destBloom`) bloque le spray.** On ne se connecte qu'à un pair qui a déjà une utilité pour la destination. Les copies ne vont donc qu'aux nœuds qui ont croisé le destinataire, ce qui ressemble plus à `fresh_spray` sans son spray aveugle. Retirer ce filtre fait passer la livraison de 12 % à 21 %.
3. Même en relâchant tous ces points, ECO-SF reste loin de DASF-V (19 % contre 33 %). Hypothèse, pas encore mesurée : le reste de l'écart viendrait de connexions d'un seul tick, avec un cooldown de 20 s par paire, sur un lien qui perd jusqu'à 30 % des paquets. À vérifier avec `connect_cooldown_s=0`, qui est beaucoup plus lent à simuler.
