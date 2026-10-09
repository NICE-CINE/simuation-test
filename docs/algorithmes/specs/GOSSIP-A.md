# GOSSIP-A — Spécification d'implémentation

**Projet :** NICE — messagerie mesh Bluetooth sans infrastructure pour grands événements
**Algorithme :** GOSSIP-A — gossip probabiliste adaptatif à la densité, avec anti-entropie et destinataire anonyme
**Statut :** alternative à DASF-V v2 et baseline sérieuse ; à comparer en simulation

> Les valeurs numériques sont des **points de départ à régler en simulation**.
> Les éléments communs avec DASF-V v2 renvoient à `docs/algorithmes/specs/DASF-V.md` (noté **[DASF §x]**).

> **Statut** : implémenté dans `src/festival_ble_sim/routing/gossip_a.py` (`--routing gossip_a`), 23 tests dans `tests/test_routing_gossip_a.py`. Le simulateur en est une réduction au niveau réseau (pas de crypto, étiquettes, preuve de travail ni SOS) : ce qui est modélisé et omis est dans `README.md` et `docs/algorithmes/gossip_a.md`.

---

## Sommaire

0. [Principe](#0-principe)
1. [Socle commun avec DASF-V](#1-socle-commun-avec-dasf-v)
2. [Adressage anonyme par étiquette](#2-adressage-anonyme-par-étiquette)
3. [Formats](#3-formats)
4. [État local](#4-état-local)
5. [Probabilité de retransmission](#5-probabilité-de-retransmission)
6. [Session et anti-entropie](#6-session-et-anti-entropie)
7. [Décision de transfert](#7-décision-de-transfert)
8. [ACK par jeton de purge](#8-ack-par-jeton-de-purge)
9. [Buffer](#9-buffer)
10. [Contrôle de charge et anti-abus](#10-contrôle-de-charge-et-anti-abus)
11. [Paramètres](#11-paramètres)
12. [Plan d'implémentation et évaluation](#12-plan-dimplémentation-et-évaluation)
13. [Limites connues](#13-limites-connues)

---

## 0. Principe

- **Aucun état de routage** : pas d'utilité, pas de communauté, pas de rang.
- **Aucune identité de destinataire** visible par les relais : chaque nœud reconnaît lui-même ses messages grâce à une étiquette cryptographique.
- À chaque contact, les nœuds comparent leurs buffers (**anti-entropie**) et se transmettent les messages manquants **avec une probabilité `p`** qui baisse quand la densité augmente.
- Les copies sont retirées par des **jetons de purge** (ACK) diffusés de façon épidémique.

**Intuition :** en foule dense, le réseau est souvent connexe sur plusieurs sauts, et une inondation contrôlée y est très efficace. En zone clairsemée, `p` remonte à 1 et l'algorithme devient une épidémie classique, peu coûteuse puisqu'il y a peu de voisins.

```
densité faible  →  p = 1            (chaque contact compte)
densité forte   →  p = C / densité  (≈ C retransmissions par voisinage)
```

---

## 1. Socle commun avec DASF-V

Repris **à l'identique** :

| Élément | Référence |
|---|---|
| Architecture en ports, cœur Kotlin en `commonMain` | [DASF §1] |
| Identités `IK`/`XK`, QR ami | [DASF §2.1] |
| Époques et `NID_e` (utilisés seulement pour les beacons et le rate-limit par pair) | [DASF §2.2–2.4] |
| BeaconShort / BeaconFull (sans `nbr_bloom` si non utilisé) | [DASF §3.3] |
| Politique batterie (l'évacuation devient une simple copie) | [DASF §10] |
| Congestion : advertising adaptatif, Trickle, scan | [DASF §11] |
| Plausibilité des beacons | [DASF §12.1] |

Ce qui **disparaît** : utilité, mules, jetons de copie, COMMIT (on copie, on ne déplace jamais), relais à 2 sauts (les relais ne savent pas qui est le destinataire).

---

## 2. Adressage anonyme par étiquette

### 2.1 Clé de paire

Chaque paire d'amis partage une clé statique, calculée hors ligne à partir des QR codes :

```
K_pair(A,B) = HKDF-SHA256( X25519(XK_A_priv, XK_B_pub),
                           info = "NICE-pair-v1" || min(IK_A, IK_B) || max(IK_A, IK_B) )
```

### 2.2 Étiquette

```
tag = HMAC-SHA256(K_pair(émetteur, destinataire), "NICE-tag-v1" || msg_id)[0..8]
```

- Les relais voient une étiquette aléatoire, différente pour chaque message : ils ne savent ni qui est le destinataire, ni si deux messages vont à la même personne.
- **Reconnaissance** : à chaque nouveau message reçu, un nœud calcule `HMAC(K_pair(ami, moi), …)` pour chacun de ses amis (~20) et compare à `tag`. 20 HMAC par message : coût négligeable.
- En cas de correspondance, le nœud tente le déchiffrement ; l'AEAD confirme (un faux positif sur 8 octets est de toute façon improbable).

### 2.3 Conséquence

Aucun relais ne peut **cibler** le trafic d'une personne, ni prioriser la livraison directe. C'est le compromis : vie privée maximale, pas de raccourci de routage.

---

## 3. Formats

### 3.1 Bundle

| Champ | Taille (o) | Nature |
|---|---|---|
| `ver` | 1 | immuable |
| `msg_id` | 16 | immuable, aléatoire |
| `tag` | 8 | immuable (§2.2) |
| `purge_hash` | 16 | immuable, `SHA-256(secret)[0..16]` (§8) |
| `prio` | 1 | immuable (0 = normal, 1 = SOS) |
| `created_at` | 4 | immuable, arrondi à la minute |
| `ttl_class` | 1 | immuable (normal 4 h, SOS 12 h) |
| `eph_pub` | 32 | immuable (X25519 éphémère) |
| `pow_nonce` | 4 | immuable (§10.2, optionnel) |
| `hops` | 1 | **mutable**, incrémenté à chaque saut |
| `ciphertext` | 256 ou 1024 (+16 tag) | chiffré, padding à classe fixe |

**Chiffrement :** comme [DASF §3.1], avec `AAD = champs immuables` et :

```
plaintext = secret (16) || sender_IK_pub (32) || Sig_IK(msg_id || contenu) (64) || contenu
```

**SOS :** ajout en clair de `sender_ek (32)` et `sos_sig (64)` pour le rate-limit SOS [DASF §3.1].

### 3.2 Jeton de purge (ACK)

```
PURGE = msg_id (16) || secret (16)      → 32 o
Valide si SHA-256(secret)[0..16] == purge_hash du bundle
```

Seul le destinataire (qui déchiffre) connaît `secret` : personne d'autre ne peut forger un jeton valide.

---

## 4. État local

```kotlin
class Holding(
  val bundle: Bundle,
  val receivedAt: Long,
  val receivedFrom: Nid,
  var forwardCount: Int,                        // nombre de fois transmis
  val seenHolders: MutableMap<Nid, Long>        // pairs vérifiés vus avec ce message (60 s)
)

class GossipState(
  val buffer: MutableMap<MsgId, Holding>,
  val purges: MutableMap<MsgId, Purge>,         // expiration = TTL max
  val deliveredIds: LruSet<MsgId>,              // messages déjà livrés à moi (anti-doublon)
  var density: Double,                          // EWMA des NID distincts sur 10 s [DASF §4]
  val friendKeys: List<Pair<IkPub, Key>>        // K_pair par ami
)
```

---

## 5. Probabilité de retransmission

```
p_base = clamp( C / max(density, 1), P_MIN, 1 )

p(m) =
  1                    si m.hops < K_FLOOD            (sortir de la zone d'origine)
  1                    si m.prio == SOS
  0                    si m.hops ≥ H_MAX
  0                    si suppressed(m)               (§5.1)
  p_base               sinon
```

- `C` ≈ nombre moyen de retransmissions voulues par voisinage (défaut 4).
- `K_FLOOD = 2` : les deux premiers sauts sont inondés (schéma GOSSIP(p, k) classique), pour éviter qu'un message meure près de sa source.
- `H_MAX` borne la propagation.

### 5.1 Suppression par compteur

```
suppressed(m) = |{ pairs vérifiés vus avec m dans les 60 dernières secondes }| ≥ K_SUP
```

Si le message est déjà présent chez `K_SUP = 3` voisins distincts, il est localement saturé : inutile de le copier davantage ici. Seuls les pairs dont le beacon est **signé et vérifié** comptent (§10.3).

### 5.2 Tirage

Le tirage est fait **une fois par (message, pair)**, pas une fois par message : un même message peut être refusé à B mais accordé à C.

---

## 6. Session et anti-entropie

### 6.1 Choix des pairs

Pas de connaissance des destinataires : le score favorise la **nouveauté** et la stabilité du lien.

```
score(B) = 5 · [B.beacon_ver a changé depuis le dernier échange]
         + 3 · [B jamais échangé dans cette époque]
         + 2 · [j'ai des SOS en buffer]
         + 1 · [B.rssiSlope ≥ 0]
         − 5 · [B.rssiSlope < −SLOPE_LEAVING]
```

`MAX_CONN = 4`, tie-break et backoff comme [DASF §6.1]. Cooldown 60 s.

### 6.2 Protocole (GATT)

```
1. HELLO       BeaconFull → vérif signature + plausibilité
2. PURGE_SYNC  échange d'un Bloom des msg_id de mes jetons de purge (1024 bits, k = 4)
               → chacun envoie les jetons que l'autre n'a pas → vérif hash → purge
3. SUMMARY     Bloom des msg_id de mon buffer (4096 bits, k = 4, ~512 o)
               + nombre de messages
4. TRANSFER    pour chaque message que B n'a pas (d'après son Bloom) :
               tirage avec p(m) (§5), file triée (§7), budget par session (§10.1)
5. CLOSE       mise à jour de seenHolders, cooldown
```

**Pourquoi un Bloom et pas une liste exacte ?** En gossip, les buffers sont gros (tous les messages de la zone) : une liste exacte de 1 000 IDs × 8 o = 8 Ko, trop long pour un contact court. Un faux positif (~2 % pour 500 messages) fait sauter un transfert, mais la redondance du gossip le compense.

> **Option** : remplacer le Bloom par une réconciliation d'ensembles (IBLT — *Invertible Bloom Lookup Table*), dont la taille dépend de la **différence** entre les deux buffers et non de leur taille. Plus complexe, à envisager si le SUMMARY devient le goulot.

### 6.3 Mise à jour de `seenHolders`

Pendant le SUMMARY, pour chaque message de mon buffer présent dans le Bloom de B (pair vérifié) : `seenHolders[B] = now`.

---

## 7. Décision de transfert

```kotlin
fun planTransfers(A: GossipState, B: PeerView): List<Holding> =
  A.buffer.values
    .filter { !B.summaryBloom.mightContain(it.bundle.msgId) }
    .filter { !it.isExpired() }
    .filter { rng.nextDouble() < p(it) }
    .sortedWith(compareBy(
      { if (it.bundle.prio == SOS) 0 else 1 },     // SOS d'abord
      { it.bundle.hops },                          // messages jeunes (peu de sauts) d'abord
      { it.forwardCount },                         // les moins diffusés d'abord
      { -it.ttlRemaining() }
    ))

fun onReceive(m: Bundle, from: Nid) {
  if (m.msgId in purges || m.msgId in buffer) return
  if (!checkPow(m)) return                          // §10.2
  m.hops += 1
  buffer[m.msgId] = Holding(m, now(), from, 0, mutableMapOf())
  if (isForMe(m)) deliver(m)                        // §2.2 — je garde aussi une copie ? non : voir §8
}
```

- **On copie toujours, on ne déplace jamais** : pas de COMMIT nécessaire. Une trame perdue coûte au pire un renvoi au prochain contact.
- Les messages « jeunes » (peu de sauts) passent en premier : ils ont le plus besoin de se répandre.

---

## 8. ACK par jeton de purge

**Livraison :**

1. `isForMe(m)` → déchiffrement → vérification de la signature de l'émetteur → livraison à l'interface.
2. Création de `PURGE = msg_id || secret`, ajout dans `purges`, reset Trickle.
3. Le destinataire **supprime** le message de son buffer (inutile de le propager davantage).
4. Doublon (déjà dans `deliveredIds`) : renvoyer simplement le jeton.

**Propagation :** épidémique, avec `p = 1` (32 o par jeton : très bon marché, et chaque jeton supprime des copies partout).

**Purge :** à la réception d'un jeton, si je détiens `msg_id` et que `SHA-256(secret)[0..16] == purge_hash` → supprimer le message. Si je ne le détiens pas, je garde le jeton pour le relayer (et pour refuser le message s'il arrive plus tard).

**Durée de vie des jetons :** jusqu'au TTL maximum du message (12 h), avec un plafond de 5 000 jetons (160 Ko), les plus anciens supprimés en premier.

---

## 9. Buffer

Le gossip remplit les buffers plus vite que le spray : capacité plus grande, et politique de suppression fondée sur la **réplication observée**.

- **Capacité :** 1 000 bundles.
- **Ordre de suppression quand le buffer est plein :**
  1. messages purgés ;
  2. messages expirés ;
  3. **les plus répliqués** : `seenHolders.size` décroissant (un message vu chez beaucoup de voisins perd peu à être supprimé ici) ;
  4. `hops` décroissant (les plus lointains de leur source) ;
  5. SOS en dernier.

---

## 10. Contrôle de charge et anti-abus

### 10.1 Charge radio

| Mécanisme | Règle |
|---|---|
| Probabilité `p` | adaptée à la densité (§5) |
| Suppression par compteur | `K_SUP` voisins suffisent (§5.1) |
| Limite de sauts | `H_MAX` |
| Budget par session | ≤ `B_SESSION = 32 Ko` envoyés par sens et par session |
| Entrée par pair | ≤ 50 bundles / min acceptés d'un même voisin |
| Advertising, Trickle, scan | comme [DASF §11] |

### 10.2 Inondation par un émetteur anonyme

Les sources étant anonymes pour les relais, on ne peut pas faire de rate-limit par source. Deux défenses :

- **Preuve de travail par message (optionnelle)** : `SHA-256(champs immuables || pow_nonce)` doit commencer par `POW_BITS = 16` bits à zéro (de l'ordre de 0,1 s de calcul sur un téléphone). Négligeable pour un utilisateur normal, coûteux pour un spammeur à grande échelle. Les SOS en sont dispensés mais restent limités par `sender_ek`.
- **Crédit d'envoi local** : `20 msg / 10 min + relayés / 5` (appliqué par l'app honnête).

### 10.3 Empoisonnement

| Attaque | Effet | Défense |
|---|---|---|
| SUMMARY Bloom rempli à 100 % | on ne lui envoie plus rien | ne nuit qu'à l'attaquant ; rejet si remplissage > attendu + 20 % |
| Faire croire que les messages sont saturés (suppression par compteur) | les autres arrêtent de les diffuser | seuls les pairs **vérifiés et distincts** comptent ; un même pair ne compte qu'une fois par 60 s ; plafond : 1 pair nouveau (< 5 min) au plus dans le compte |
| Faux jetons de purge | impossible | vérification du `purge_hash` |
| Rejouer d'anciens messages | charge inutile | `msg_id` dans `purges` → refus ; TTL |

---

## 11. Paramètres

| Paramètre | Défaut | À régler ? |
|---|---|---|
| `C` (retransmissions par voisinage) | 4 | **oui** |
| `P_MIN` | 0,05 | **oui** |
| `K_FLOOD` | 2 | oui |
| `H_MAX` | 15 | **oui** |
| `K_SUP` / fenêtre | 3 / 60 s | **oui** |
| SUMMARY Bloom | 4096 bits, k = 4 | non |
| PURGE_SYNC Bloom | 1024 bits, k = 4 | non |
| `B_SESSION` | 32 Ko | oui |
| Buffer | 1 000 bundles | oui |
| Jetons de purge max | 5 000 | non |
| `POW_BITS` | 16 (0 = désactivé) | oui |
| TTL normal / SOS | 4 h / 12 h | non |
| `MAX_CONN`, cooldown | 4 / 60 s | non |

---

## 12. Plan d'implémentation et évaluation

### 12.1 Ordre

1. Réutiliser le simulateur et le socle DASF-V (ports, beacons, batterie).
2. Étiquettes (§2) et jetons de purge (§8) — simples et testables unitairement.
3. Anti-entropie avec Bloom (§6) et `p` constant → c'est une **épidémie pure**, première baseline.
4. `p` adaptatif, `K_FLOOD`, `H_MAX`.
5. Suppression par compteur et politique de buffer « les plus répliqués d'abord ».
6. Protections (§10) : budget de session, preuve de travail, plausibilité.
7. Option IBLT si le SUMMARY s'avère être le goulot.

### 12.2 Métriques

Identiques à [DASF §15.2], plus :

- **taille moyenne du SUMMARY** et part du temps de contact qu'il consomme ;
- **nombre de copies par message** au moment de la livraison (redondance réelle) ;
- **délai de propagation des jetons de purge** (temps avant que 90 % des copies soient supprimées).

### 12.3 Scénarios clés

- **Jour dense vs nuit clairsemée** : c'est là que le gossip est le plus fort puis le plus faible.
- Taux d'adoption 5 / 10 / 30 %.
- Charge de trafic croissante (messages / utilisateur / heure) : trouver le point où l'overhead s'effondre.

### 12.4 Ablation

`p` constant vs adaptatif, sans `K_FLOOD`, sans suppression par compteur, buffer FIFO vs « plus répliqués d'abord ».

---

## 13. Limites connues

| Limite | Effet | Piste |
|---|---|---|
| **Pas de direction** : les relais ignorent le destinataire | Latence élevée si le destinataire est loin et la densité faible | Accepter ; ou hybride avec un indice de zone ([option « boîtes aux lettres de zone »]) |
| **Overhead mal borné** sous forte charge | Saturation des buffers et du temps de contact | `C`, `P_MIN`, `H_MAX`, `B_SESSION` ; mesurer le point de rupture |
| **Buffers très sollicités** | Pertes par éviction | Politique « plus répliqués d'abord » |
| **SUMMARY coûteux** sur contacts courts | Échanges incomplets | Bloom compact, option IBLT |
| **Faux positifs du Bloom SUMMARY** | Transferts manqués | Compensés par la redondance ; mesurer |
| **Inondation par un émetteur anonyme** | DoS | Preuve de travail, entrée par pair, crédit d'envoi |
| **Coût de reconnaissance des étiquettes** | Croît avec le nombre d'amis × messages reçus | Négligeable jusqu'à ~100 amis ; au-delà, étiquettes indexées par époque |
| **Batterie** : chaque nœud relaie une grande part du trafic de sa zone | Consommation plus élevée que les approches à jetons | Politique batterie [DASF §10], `P_MIN` plus bas en batterie faible |
