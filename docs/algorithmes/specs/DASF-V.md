# DASF-V v2 — Spécification d'implémentation

**Projet :** NICE — messagerie mesh Bluetooth sans infrastructure pour grands événements (festivals, stades)
**Algorithme :** DASF-V v2 — *Density-Aware Spray-and-Focus with Verifiable ACK/purge*
**Contexte cible :** ~10 000 personnes, taux d'adoption variable, BLE uniquement, Android + iOS (KMM)

> Les valeurs numériques de ce document sont des **points de départ à régler en simulation**, pas des valeurs définitives.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/dasfv.py` (`--routing dasfv`), 24 tests dans `tests/test_routing_dasfv.py`. Le simulateur en est une réduction au niveau réseau (pas de crypto, GATT, SOS ni époques) : ce qui est modélisé et omis est dans `README.md` et `docs/algorithmes/dasfv.md`.

---

## Sommaire

0. [Objectifs et principes](#0-objectifs-et-principes)
1. [Architecture](#1-architecture)
2. [Identités, clés et pseudonymes](#2-identités-clés-et-pseudonymes)
3. [Formats](#3-formats)
4. [État local](#4-état-local)
5. [Voisinage, densité, fraîcheur, mules](#5-voisinage-densité-fraîcheur-mules)
6. [Choix des pairs et session](#6-choix-des-pairs-et-session)
7. [Décision de routage](#7-décision-de-routage)
8. [ACK et purge](#8-ack-et-purge)
9. [Buffer](#9-buffer)
10. [Politique batterie](#10-politique-batterie)
11. [Congestion et rate-limits](#11-congestion-et-rate-limits)
12. [Contrôles de sécurité](#12-contrôles-de-sécurité)
13. [Changement d'époque](#13-changement-dépoque)
14. [Paramètres](#14-paramètres)
15. [Plan d'implémentation et évaluation](#15-plan-dimplémentation-et-évaluation)
- [Annexe A — Limites et réponses](#annexe-a--limites-et-réponses)
- [Annexe B — Limites ouvertes](#annexe-b--limites-ouvertes)

---

## 0. Objectifs et principes

Trois objectifs contradictoires :

1. **Maximiser le taux de livraison**
2. **Minimiser la latence** entre l'envoi et la réception
3. **Ne pas surcharger le réseau** (radio, buffers, batterie)

Aucun algorithme ne maximise les trois à la fois : Epidemic maximise livraison et latence au prix d'une inondation ; Spray-and-Wait économise le réseau mais la latence explose quand la densité baisse. DASF-V v2 est un algorithme **adaptatif** qui se place sur le front de Pareto selon le contexte local (densité, mobilité, batterie), avec des paramètres explicites pour régler le compromis.

**Principes de conception :**

- **Livraison directe d'abord** (destination à 1 ou 2 sauts) : latence minimale, zéro inondation.
- **Spray adaptatif à la densité** : peu de copies en zone dense, plus en zone clairsemée, avec un plancher de redondance.
- **Focus par gradient d'utilité** (PRoPHET) : chaque copie se rapproche de la destination.
- **Mules** : nœuds très mobiles utilisés pour franchir les « cercles sociaux » et le démarrage à froid, avec des dégâts bornés s'ils sont malveillants.
- **Transfert avec garde** (COMMIT) : une copie n'est supprimée qu'une fois le saut suivant confirmé.
- **ACK signés** par la destination : purge vérifiable, impossible à forger.
- **Fraîcheur tirée à la demande** plutôt que poussée par plus de beacons.
- **Chiffrement de bout en bout** du contenu, métadonnées de routage authentifiées et contrôlées en plausibilité.

---

## 1. Architecture

Le cœur de l'algorithme est du **Kotlin pur dans `commonMain`**, sans aucune dépendance BLE. Il ne parle au monde extérieur qu'à travers des interfaces (ports) :

| Interface (port) | Rôle | Implémentations |
|---|---|---|
| `RadioPort` | advertiser, scanner, connexions, envoi de trames | Android BLE, iOS CoreBluetooth, simulateur |
| `CryptoPort` | X25519, Ed25519, HKDF, ChaCha20-Poly1305, SHA-256 | libsodium / Android Keystore / iOS Secure Enclave |
| `SensorPort` | batterie, podomètre | OS, simulateur |
| `Clock` | temps monotone et temps réel | système, horloge simulée |

Le **même cœur** tourne ainsi sur les téléphones et dans un simulateur JVM : tests déterministes et reproductibles.

**Modules du cœur :**

| Module | Responsabilité |
|---|---|
| `NeighborManager` | beacons, densité, fraîcheur, score de mule |
| `SecurityManager` | identités, époques, signatures, plausibilité, réputation |
| `Router` | buffer, utilités, décisions spray/focus |
| `SessionManager` | protocole d'échange pendant un contact |
| `EnergyManager` | politique batterie |
| `CongestionManager` | Trickle, rate-limits |

---

## 2. Identités, clés et pseudonymes

### 2.1 Clés long terme

Générées à l'installation, stockées dans le Keystore / Secure Enclave :

- `IK` : paire Ed25519 (identité)
- `XK` : paire X25519 (chiffrement de bout en bout)

**QR code « ami »** : `IK_pub`, `XK_pub`, nom affiché. C'est la seule façon de pouvoir écrire à quelqu'un (hypothèse d'usage : retrouver son groupe).

### 2.2 Époques

```
e = floor((t − T0) / EPOCH_LEN)
EPOCH_LEN = 24 h
T0 = heure creuse (ex. 6 h du matin, heure locale du festival), fixé dans la configuration
```

### 2.3 Clé d'époque par key blinding

Même principe que les services onion v3 de Tor :

```
h_e       = SHA-256("NICE-blind-v1" || IK_pub || e)   (réduit modulo l'ordre du groupe)
EK_e_pub  = h_e · IK_pub      → calculable par quiconque connaît IK_pub (les amis)
EK_e_priv = h_e · IK_priv     → calculable seulement par le propriétaire
```

Les relais qui ne connaissent pas `IK_pub` ne peuvent pas relier `EK_e` et `EK_{e+1}`.

### 2.4 Identifiant de routage

```
NID_e = SHA-256(EK_e_pub)[0..8]    (8 octets)
```

Propriétés obtenues :

- un ami calcule le `NID` de sa destination **hors ligne** ;
- personne ne peut usurper un `NID` sans la clé privée (les beacons sont signés par `EK_e`) ;
- les relais vérifient les ACK avec `dest_ek`, présent dans l'en-tête du message.

> ⚠️ **Point délicat.** Signer avec un scalaire « aveuglé » n'est pas une opération Ed25519 standard. libsodium expose les primitives bas niveau nécessaires, mais la signature doit être écrite à la main, avec soin.
> **Repli pour le prototype :** utiliser directement `IK` (identifiants liables d'une époque à l'autre), puis ajouter le blinding.

### 2.5 Mode certifié (optionnel, anti-Sybil)

À l'inscription en ligne (avant le festival), l'organisateur délivre une **signature aveugle** (RSA-BSSA, RFC 9474) sur chaque `EK_e_pub` : une par jour de festival et par billet.

- Un billet = une identité par époque.
- Le jeton `Cred_e` (~256 o) est présenté **une fois par pair et par époque** en session, puis mis en cache.
- La signature aveugle empêche l'organisateur de relier `Cred_e` au billet.

---

## 3. Formats

### 3.1 Bundle (message)

| Champ | Taille (o) | Nature |
|---|---|---|
| `ver` | 1 | immuable |
| `msg_id` | 16 | immuable, aléatoire |
| `dest_ek` | 32 | immuable (`EK_e_pub` de la destination) |
| `epoch` | 2 | immuable |
| `prio` | 1 | immuable (0 = normal, 1 = SOS) |
| `created_at` | 4 | immuable, arrondi à la minute |
| `ttl_class` | 1 | immuable (normal 4 h, SOS 12 h) |
| `eph_pub` | 32 | immuable (X25519 éphémère) |
| `tokens` | 1 | **mutable** — jetons de copie portés |
| `flags` | 1 | **mutable** — `mule_replicated` |
| `ciphertext` | 256 ou 1024 (+16 tag) | chiffré, padding à classe fixe |

Le `NID` de destination est dérivé de `dest_ek` : il n'est pas transmis.

**Chiffrement de bout en bout :**

```
k  = HKDF-SHA256(X25519(eph_priv, dest_XK_pub), info = "NICE-msg-v1")
ct = ChaCha20-Poly1305(k, nonce = 0, AAD = champs immuables, plaintext)
plaintext = sender_IK_pub (32) || Sig_IK(msg_id || contenu) (64) || contenu
```

- Le nonce nul est sûr : la clé ne sert qu'une fois (éphémère par message).
- L'émetteur est **invisible pour les relais** mais authentifié pour le destinataire.
- Toute modification de l'en-tête par un relais est détectée par l'AEAD.

**Cas SOS :** ajout en clair de `sender_ek (32)` et `sos_sig (64)` pour que les relais appliquent le rate-limit SOS. L'anonymat de l'émetteur est sacrifié pour ce cas.

### 3.2 ACK

```
ACK = msg_id (16) || dest_ek (32) || Sig_{EK_e}("NICE-ACK-v1" || msg_id) (64)    → 112 o
```

### 3.3 Beacons

**BeaconShort** (advertising classique, ≤ 31 o) :

- UUID de service
- `NID` tronqué (4 o)
- `flags` (1 o) : mule, batterie (2 bits), a-des-messages
- `beacon_ver` (1 o), incrémenté à chaque changement du BeaconFull

Sur iOS en arrière-plan, seul l'UUID est visible : le reste passe par GATT.

**BeaconFull** (extended advertising ≤ 255 o, sinon caractéristique GATT) :

| Champ | Taille (o) |
|---|---|
| `ver`, `epoch` | 3 |
| `EK_e_pub` | 32 |
| densité, zones, batterie, flags | 4 |
| `nbr_bloom` (60 voisins max, 512 bits, k = 3) | 64 |
| `ack_bloom` (512 bits, k = 3) | 64 |
| `timestamp` | 4 |
| `sig` (par `EK_e`) | 64 |
| **Total** | **≈ 235** |

Le `nbr_bloom` ne contient que les **60 voisins au RSSI le plus fort** : taux de faux positifs ~2–3 %, et contrôle de plausibilité possible.

---

## 4. État local

```kotlin
class Holding(                      // un message dans le buffer
  val bundle: Bundle,
  var tokens: Int,
  var uncertainTokens: Int,         // transferts sans COMMIT confirmé
  var uncertainSince: Long?,
  val receivedAt: Long,
  val seenHoldersNearby: MutableMap<Nid, Long>   // pour la purge copy-aware
)

class Neighbor(
  val nid: Nid,
  var ek: PubKey?, var verified: Boolean, var credOk: Boolean,
  var lastSeen: Long, var rssiEwma: Double, var rssiSlope: Double,
  var beacon: BeaconFull?, var beaconAt: Long,
  var isMule: Boolean, var battery: Level,
  var cooldownUntil: Long,
  val firstSeen: Long
)

class UtilityTable(                 // PRoPHET
  val p: MutableMap<Nid, Float>,
  var lastAging: Long
)

class Reputation(var given: Int, var ackSeen: Int)   // par pair et par époque

class AckStore                      // msg_id -> Ack, expiration = TTL du message
```

Le `NeighborManager` maintient en plus :

- `density` : EWMA du nombre de `NID` distincts entendus sur 10 s ;
- deux générations de voisinage (courante / précédente), rotation toutes les 5 s ;
- 16 signatures MinHash de zones (32 hashs chacune) ;
- `turnover`, `stepsPerMin`, `zones30min`.

---

## 5. Voisinage, densité, fraîcheur, mules

### 5.1 Réception d'un beacon

1. Mettre à jour `lastSeen`, `rssiEwma`, `rssiSlope` (pente d'une régression sur les 5 dernières mesures).
2. Si `beacon_ver` a changé : marquer le BeaconFull à relire.
3. Vérifier la signature **seulement** lors d'une lecture de BeaconFull, puis mettre `EK` en cache pour l'époque.

### 5.2 Fraîcheur

| Information | Valide si |
|---|---|
| Voisin à 1 saut | `now − lastSeen ≤ 10 s` |
| Information à 2 sauts (`nbr_bloom` de B) | `now − B.beaconAt ≤ 5 s` |

**Vérification à la demande :** quand B reçoit un message en relais à 2 sauts, il lance `targetedScan(dest_nid, 2 s, duty élevé)`.

- Destination trouvée → livraison.
- Sinon → B garde le message comme copie focus. **Un détour, jamais une perte.**

La fraîcheur est ainsi payée uniquement quand elle sert, sans augmenter le rythme global des beacons.

### 5.3 Score de mule

Recalculé toutes les 60 s :

```
turnover = EWMA(1 − Jaccard(N(t), N(t − 60 s)))

toutes les 2 min : MinHash du voisinage courant
  si similarité max avec les signatures stockées < 0,2 → nouvelle zone

isMule = zones30min ≥ 3
       ∧ stepsPerMin ≥ 30          (podomètre : distingue marcher / voir défiler la foule)
       ∧ batterie ≥ 40 %
       ∧ relayMode activé           (rôle volontaire)
```

---

## 6. Choix des pairs et session

### 6.1 Choix des pairs

Toutes les secondes, classement des voisins valides hors cooldown :

```
score(B) = 10 · [j'ai un message pour B]
         +  5 · [j'ai un message pour un NID dans B.nbr_bloom]
         +  3 · [B.isMule]
         +  2 · [B.battery ≥ moyen]
         +  1 · [B.rssiSlope ≥ 0]
         −  5 · [B.rssiSlope < −SLOPE_LEAVING]
```

- Au plus `MAX_CONN = 4` connexions simultanées.
- Connexion croisée : le `NID` le plus petit initie.
- Backoff aléatoire : `[0, 200 ms × min(density / 20, 5)]`.
- Cooldown de 60 s après une session complète, sauf si `beacon_ver` change ou si un nouveau message concerne le pair.

### 6.2 Protocole de session (GATT, MTU négocié ≥ 247)

```
1. HELLO      échange BeaconFull (+ Cred_e au 1er contact de l'époque)
              → vérif signature, plausibilité, credential
              → échec ⇒ abandon + pénalité

2. ACK_SYNC   chacun envoie les msg_id (tronqués à 8 o) des ACK qu'il possède
              et dont le bit est absent du bloom de l'autre
              → l'autre demande → envoi des ACK complets

3. PURGE      pour chaque ACK reçu : si je détiens le message et que dest_ek correspond
              → vérifier la signature → supprimer la copie + stocker l'ACK

4. SUMMARY    liste EXACTE des msg_id tronqués (8 o) de mon buffer
              (pas de Bloom : aucun faux positif qui bloquerait un transfert)

5. UTIL_REQ   « donne-moi ton utilité pour ces NID » (≤ 64) → réponses sur 1 octet

6. TRANSFER   file triée (§7) ; chaque bundle est fragmenté en trames
              envoyées en write-with-response ; fin de bundle → B renvoie COMMIT(msg_id)

7. CLOSE      mise à jour utilité, réputation, cooldown
```

La coupure du contact peut survenir à n'importe quelle étape : l'ordre garantit que le plus utile (les ACK, puis les livraisons directes) passe en premier.

### 6.3 Gestion de COMMIT

- **COMMIT reçu** : A applique la décrémentation de jetons ou supprime sa copie.
- **COMMIT non reçu** : les jetons concernés passent en `uncertainTokens`.
  - Si A recroise B dans l'époque : `HAVE(msg_id)` pour réconcilier.
  - Sinon, après `T_UNCERTAIN = 10 min` : A divise ses jetons par deux (minimum 1).
  - L'inflation de copies reste bornée.

---

## 7. Décision de routage

### 7.1 Budget de copies à la création

```
L = clamp( round( L_base(prio) · sqrt(D_REF / max(density, 1)) ), k_min(prio), L_MAX )

L_base : normal 8, SOS 16
k_min  : normal 2, SOS 4
L_MAX  : 32
D_REF  : 20
```

### 7.2 File de transfert de A vers B

```kotlin
fun planTransfers(A: Node, B: Neighbor): List<Transfer> {
  val out = mutableListOf<Transfer>()
  for (h in A.buffer.filter { it.bundle.msgId !in B.summary }) {
    val d  = h.bundle.destNid
    val uA = A.util[d]
    val uB = min(B.util[d], utilCap(B))
    when {
      // 1. livraison directe
      d == B.nid ->
        out += Transfer(h, tokens = h.tokens, move = true, rank = 1)

      // 2. SOS en spray
      h.bundle.prio == SOS && h.tokens > 1 ->
        out += Transfer(h, half(h, B), move = false, rank = 2)

      // 3. relais à 2 sauts
      B.nbrBloomFresh() && d in B.nbrBloom && B.rssiSlope >= -SLOPE_LEAVING ->
        out += Transfer(h, 1, move = (h.tokens == 1), rank = 3)

      // 4. spray
      h.tokens > 1 ->
        out += Transfer(h, half(h, B), move = false, rank = 4)

      // 5. focus par gradient d'utilité
      uB > uA + DELTA ->
        out += Transfer(h, 1, move = true, rank = 4)

      // 6. démarrage à froid : réplication vers une mule
      uA < EPS && B.isMule && !h.bundle.muleReplicated ->
        out += Transfer(h, 1, move = false, replicate = true, rank = 5)
    }
  }
  return out.sortedWith(compareBy({ it.rank }, { it.h.ttlRemaining() }))
}

// une mule reçoit au plus 1/3 des jetons d'un porteur
fun half(h: Holding, B: Neighbor) =
  if (B.isMule) max(1, h.tokens / 3) else h.tokens / 2
```

### 7.3 Règles

- `move = true` : A supprime sa copie **après** COMMIT.
- `move = false` : A retranche les jetons donnés **après** COMMIT.
- `replicate` : A garde son jeton ; la copie de B porte `muleReplicated = true`.
  - Chaque copie focus ne peut être répliquée qu'une fois vers une mule → total ≤ 2L.
  - En démarrage à froid, la dernière copie n'est jamais **déplacée** vers une mule : elle ne dépend jamais d'une seule mule.
- `utilCap(B) = 0.5` si B est vu depuis moins de 5 min, sans credential et de réputation inconnue ; sinon pas de plafond.

### 7.4 Utilité PRoPHET

Unité de vieillissement : 30 s.

```
rencontre      : P(A,B) ← P(A,B) + (1 − P(A,B)) · P_INIT
vieillissement : P      ← P · γ^k
transitivité   : P(A,C) ← max(P(A,C), P(A,B) · P(B,C) · β)
                 (uniquement pour les NID demandés en UTIL_REQ)
```

---

## 8. ACK et purge

**Réception d'un message par sa destination :**

1. déchiffrer, vérifier la signature de l'émetteur ;
2. livrer à l'interface ;
3. créer l'ACK, le stocker ;
4. déclencher un reset Trickle.

Doublon : renvoyer simplement l'ACK.

**Propagation :** épidémique (112 o, bon marché), bit correspondant dans `ack_bloom`, rotation de génération toutes les 60 s.

**Purge :** uniquement après vérification de la signature contre le `dest_ek` du bundle détenu. Un nœud qui ne détient pas le message stocke et relaie l'ACK sans avoir besoin de le vérifier.

---

## 9. Buffer

- **Capacité :** 500 bundles (2 000 pour une mule).
- **Ordre de suppression quand le buffer est plein :**
  1. messages acquittés ;
  2. messages expirés ;
  3. **purge copy-aware** (priorité normale uniquement) : `tokens == 1`, ≥ `k_min` voisins distincts vus avec ce message dans leur SUMMARY dans les 60 dernières secondes, buffer > 80 % ;
  4. messages normaux, par `uA(dest) × tokens` croissant, puis du plus ancien au plus récent ;
  5. SOS en dernier.

---

## 10. Politique batterie

| Batterie | Comportement |
|---|---|
| ≥ 50 % | normal ; accepte les évacuations (si buffer < 70 %) |
| < 40 % | perd le statut de mule |
| < 30 % | évacue progressivement les messages normaux (move avec COMMIT) vers des pairs ≥ 50 % |
| < 15 % | évacue tout, SOS compris ; n'accepte plus que les messages qui lui sont destinés ; scan minimal |
| aucun pair éligible | garde ses messages, passe en veille basse consommation |

La batterie n'est annoncée que sur **3 niveaux** (bas / moyen / haut).

---

## 11. Congestion et rate-limits

| Mécanisme | Règle |
|---|---|
| Intervalle d'advertising | `clamp(100 ms × density / 10, 100 ms, 2 s)` |
| Mise à jour du BeaconFull | Trickle : `Imin` 500 ms, `Imax` 8 s, suppression si k = 3 voisins ont annoncé la même info |
| Reset Trickle | nouvel ACK, nouveau message, ou turnover > 0,5 — **au plus 1 reset / 2 s** |
| Duty cycle du scan | 30 % / 10 % / 5 % selon batterie |
| Extended advertising | payload sur canaux de données → libère les canaux 37/38/39 |
| Entrée par pair | ≤ 50 bundles / min acceptés d'un même voisin |
| SOS | ≤ 3 / heure par `sender_ek`, appliqué par les relais |
| Envoi local | `20 msg / 10 min + relayés / 5` (crédit donnant-donnant) |

---

## 12. Contrôles de sécurité

### 12.1 Plausibilité d'un beacon

Rejet si :

- remplissage du `nbr_bloom` > 0,45 (attendu ≈ 0,30 pour 60 voisins) ;
- remplissage du `ack_bloom` > 0,6 ;
- `timestamp` décalé de plus de 30 s ;
- nombre de voisins annoncé > 2 × ma propre densité + 20.

Un rejet de plausibilité **dévalue** le pair ; une signature invalide l'**exclut**.

### 12.2 Réputation

Par pair et par époque :

```
score = (ackSeen + 1) / (given + 2)
si given ≥ 10 et score < 0,05 → pair ignoré pour l'époque
```

Signal faible (un ACK peut provenir d'une autre copie), d'où le seuil très bas.

### 12.3 Nouvelles identités

Utilité plafonnée (`utilCap`). En mode certifié, plafond levé.

---

## 13. Changement d'époque

À `T0 + n × 24 h`, chaque nœud :

1. calcule `EK_{e+1}` et `NID_{e+1}` ;
2. **réinitialise la table d'utilité et la réputation** ;
3. **garde son buffer**.

**Période de grâce de 2 h :** le nœud répond encore à `NID_e` pour les messages en vol. Pendant ces 2 h, `NID_e` et `NID_{e+1}` sont liables : fuite de vie privée acceptée, à une heure creuse.

L'émetteur calcule toujours `dest_ek` avec l'époque courante au moment de la création du message.

---

## 14. Paramètres

| Paramètre | Défaut | À régler ? |
|---|---|---|
| `L_base` normal / SOS | 8 / 16 | **oui** |
| `k_min` normal / SOS | 2 / 4 | **oui** |
| `L_MAX`, `D_REF` | 32, 20 | non |
| `DELTA` (hystérésis focus) | 0,1 | **oui** |
| `P_INIT`, `β`, `γ` (par 30 s) | 0,75 ; 0,25 ; 0,98 | γ oui |
| `EPS` (utilité ≈ 0) | 0,01 | non |
| Validité 1 saut / 2 sauts | 10 s / 5 s | oui |
| `SLOPE_LEAVING` | −2 dB/s | oui |
| Mule : zones / pas / batterie | 3 / 30 par min / 40 % | oui |
| `MAX_CONN` | 4 | non |
| Cooldown pair | 60 s | non |
| `T_UNCERTAIN` | 10 min | non |
| TTL normal / SOS | 4 h / 12 h | non |
| Buffer normal / mule | 500 / 2 000 | non |
| `EPOCH_LEN` / grâce | 24 h / 2 h | **oui** (arbitrage vie privée / performance) |
| Seuils de plausibilité | 0,45 / 0,6 | oui |

---

## 15. Plan d'implémentation et évaluation

### 15.1 Ordre d'implémentation

1. **Simulateur minimal** (JVM, événements discrets) avec ports simulés et mobilité festival : scènes, bars, camping, attraction selon la programmation. Baselines : Epidemic, PRoPHET, Spray-and-Wait. Le cœur étant en Kotlin, il peut aussi être branché dans The ONE via un adaptateur `MessageRouter`.
2. Buffer + spray/focus + utilité PRoPHET, sans sécurité ni BLE.
3. ACK et purge (sans signature d'abord), puis COMMIT et jetons incertains.
4. `NeighborManager` : blooms, fraîcheur, relais à 2 sauts, scan ciblé.
5. Mules et politique batterie.
6. Sécurité : chiffrement de bout en bout, signatures (sans blinding d'abord), plausibilité, réputation, puis key blinding.
7. `RadioPort` Android, puis iOS ; mesure réelle de la découverte en arrière-plan.
8. Test terrain à 20–50 téléphones : durée des contacts, portée en foule, comportement du RSSI.

### 15.2 Métriques

- taux de livraison ;
- latence médiane et p95 ;
- overhead (relais ÷ livrés) ;
- octets émis et nombre de connexions (proxy énergie) ;
- occupation des buffers.

### 15.3 Scénarios

- taux d'adoption : 5 / 10 / 30 % ;
- jour / nuit (densité et batterie) ;
- plusieurs modèles de mobilité (robustesse) ;
- si disponibles : traces réelles de rencontres Bluetooth (ex. Haggle / CRAWDAD — disponibilité à vérifier).

### 15.4 Ablation

v2 complète, puis sans mules, sans relais 2 sauts, sans COMMIT, sans purge copy-aware, avec `k_min = 1`, etc., pour isoler l'apport de chaque mécanisme.

---

## Annexe A — Limites et réponses

Statuts : **résolu** · **atténué** · **ouvert** · **assumé** (choix de périmètre ou limite fondamentale).

### Mules

| Limite | Réponse | Statut |
|---|---|---|
| Turnover relatif : un nœud immobile près d'un flux passe pour une mule | Combiner turnover et podomètre | résolu |
| Bouger beaucoup ≠ aller loin | Score = nombre de zones distinctes (MinHash des voisinages) | atténué |
| Statut de mule auto-déclaré → vecteur de blackhole | Au plus 1/3 des jetons à une mule ; jamais la dernière copie déplacée vers une mule seule | atténué |
| Mules surchargées | Rôle volontaire, désactivé sous 40 %, buffer plafonné | atténué |

### Transfert avec garde

| Limite | Réponse | Statut |
|---|---|---|
| Aller-retour supplémentaire | Write-with-response GATT, COMMIT regroupés | résolu |
| Copies dupliquées si COMMIT perdu | Jetons incertains, réconciliation `HAVE`, division par deux après 10 min | atténué |

### Redondance

| Limite | Réponse | Statut |
|---|---|---|
| Point de défaillance unique en focus | `k_min`, COMMIT, évacuation batterie | résolu |
| Surcoût du plancher en zone dense | `k_min` par priorité + purge copy-aware | atténué |

### Batterie

| Limite | Réponse | Statut |
|---|---|---|
| Effet cascade en fin de nuit | Évacuation progressive (30 % puis 15 %), réception conditionnée, veille si aucun pair éligible | atténué |
| Fuite / mensonge sur la batterie | 3 niveaux seulement ; mensonge borné par les plafonds | atténué |

### Fraîcheur et radio

| Limite | Réponse | Statut |
|---|---|---|
| Fraîcheur vs nombre de beacons | Fraîcheur tirée à la demande (scan ciblé), resets Trickle limités | résolu |
| RSSI bruité | Lissage, usage en départage seulement ; un échec = détour, pas perte | atténué |
| Saturation des canaux 37/38/39 | Intervalle adapté à la densité, extended advertising, gigue, `MAX_CONN` | atténué |
| Téléphones sans BLE 5 | Double mode : BeaconShort + lecture GATT | résolu |
| Restrictions iOS en arrière-plan | Tout par GATT côté iOS, Android en advertiser principal | ouvert |

### Sécurité

| Limite | Réponse | Statut |
|---|---|---|
| Sybil | Mode certifié : billet = identité (signature aveugle de l'organisateur) | résolu si organisateur partenaire, sinon ouvert |
| Whitewashing | Identités coûteuses en mode certifié ; sinon plafond pour les nouveaux | idem |
| Empoisonnement des Bloom filters | Beacons signés + contrôles de plausibilité relatifs à la densité mesurée | atténué |
| Faux rejets par la plausibilité | Seuils relatifs à ma densité ; dévaluation plutôt qu'exclusion | résolu |
| Blackhole | Plafond d'utilité, réputation locale, bornes sur les mules | atténué |
| Faux ACK | ACK signés par `EK_e` de la destination, vérifiés avant purge | résolu |
| Abus de la priorité SOS | SOS signés + ≤ 3 / h par émetteur | résolu |
| Coût CPU des signatures | Vérification uniquement des pairs en session, cache par époque | résolu |

### Vie privée

| Limite | Réponse | Statut |
|---|---|---|
| Reset de l'utilité à chaque époque | Époques longues calées sur une heure creuse ; `EPOCH_LEN` comme paramètre explicite | ouvert (arbitrage) |
| Clé du destinataire requise à l'avance | QR code entre amis ; cohérent avec l'usage | assumé |
| Métadonnées dans l'en-tête | Padding à tailles fixes, TTL arrondi, 2 niveaux de priorité, émetteur chiffré | atténué |
| Liaison des NID pendant la période de grâce | 2 h à heure creuse | assumé |

### Limites générales

| Limite | Réponse | Statut |
|---|---|---|
| Contacts trop courts | Ordre de priorité des transferts (ACK → direct → SOS → 2 sauts → TTL) | atténué |
| Pas de garantie de délai ; destination partie | Statuts « en transit » / « livré » côté interface | assumé (inhérent au DTN) |
| Messages de groupe | Clé de groupe, utilité = max des membres | travaux futurs |
| Contenus lourds | Texte seulement, ~1 Ko max | assumé |
| Nœuds égoïstes | Crédit d'envoi donnant-donnant | atténué |
| Démarrage à froid de l'utilité | Réplication vers mule quand l'utilité ≈ 0 | atténué |
| Faux positifs du summary vector | Liste exacte de `msg_id` tronqués au lieu d'un Bloom | résolu |
| Validité de la simulation | Plusieurs modèles de mobilité, traces réelles, test terrain | atténué |
| Explosion du nombre de paramètres | 3–4 paramètres clés réglés, le reste fixé ; sensibilité + ablation | atténué |

---

## Annexe B — Limites ouvertes

Quatre limites restent structurelles et doivent être **présentées comme telles, mesurées et discutées** :

1. **Sybil sans partenariat avec l'organisateur** : sans ancrage d'identité coûteux, aucune défense hors ligne complète.
2. **Arbitrage vie privée / routage** : l'utilité liée à une identité s'oppose à l'unlinkabilité ; `EPOCH_LEN` matérialise ce compromis.
3. **Découverte BLE en arrière-plan sur iOS** : contrainte de la plateforme, qu'aucun algorithme ne contourne.
4. **Validité de la simulation** : en l'absence de traces réelles de festival, les résultats dépendent du modèle de mobilité.
