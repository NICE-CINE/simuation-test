# BUBBLE-F — Spécification d'implémentation

**Projet :** NICE — messagerie mesh Bluetooth sans infrastructure pour grands événements
**Algorithme :** BUBBLE-F — routage social inspiré de BUBBLE Rap (Hui, Crowcroft, Yoneki, 2008), adapté au festival
**Statut :** alternative à DASF-V v2, à comparer en simulation

> Les valeurs numériques sont des **points de départ à régler en simulation**.
> Les éléments communs avec DASF-V v2 renvoient à `docs/algorithmes/specs/DASF-V.md` (noté **[DASF §x]**).

> **Statut** : implémenté dans `src/festival_ble_sim/routing/bubble_f.py` (`--routing bubble_f`), 23 tests dans `tests/test_routing_bubble_f.py`. Le simulateur en est une réduction au niveau réseau (pas de Bloom, `rankCap`, SOS ni RSSI ; vues exactes via l'instance partagée, époques optionnelles avec `epoch_s`) : ce qui est modélisé et omis est dans `README.md` et `docs/algorithmes/bubble_f.md`.

---

## Sommaire

0. [Principe](#0-principe)
1. [Socle commun avec DASF-V](#1-socle-commun-avec-dasf-v)
2. [Notions sociales](#2-notions-sociales)
3. [État local](#3-état-local)
4. [Détection de communauté (SIMPLE adapté)](#4-détection-de-communauté-simple-adapté)
5. [Centralités (C-Window)](#5-centralités-c-window)
6. [Session](#6-session)
7. [Décision de routage](#7-décision-de-routage)
8. [Anti-blocage et anti-blackhole](#8-anti-blocage-et-anti-blackhole)
9. [Buffer et charge des nœuds centraux](#9-buffer-et-charge-des-nœuds-centraux)
10. [Changement d'époque](#10-changement-dépoque)
11. [Paramètres](#11-paramètres)
12. [Plan d'implémentation et évaluation](#12-plan-dimplémentation-et-évaluation)
13. [Limites connues](#13-limites-connues)

---

## 0. Principe

Deux observations sur les réseaux humains :

1. **Les gens forment des communautés** (groupes d'amis, collègues, campement commun) et se croisent beaucoup à l'intérieur.
2. **Certains nœuds sont plus centraux** que d'autres : ils rencontrent beaucoup de monde différent.

Le message « monte » vers des nœuds de plus en plus centraux **globalement**, jusqu'à entrer dans la **communauté du destinataire** (la « bulle »). À l'intérieur, il monte vers des nœuds plus centraux **localement** (dans la communauté) jusqu'au destinataire.

**Adaptation festival :** les communautés sont amorcées gratuitement par le **graphe des QR codes** échangés entre amis. Les amis du destinataire sont souvent physiquement proches de lui : entrer dans sa bulle, c'est presque l'atteindre.

```
   A (hors bulle)                          bulle de D
   rang global 12 ──► rang global 40 ──►  ┌────────────────────────┐
                                          │ rang local 3 ──► rang   │
                                          │ local 9 ──► D           │
                                          └────────────────────────┘
```

---

## 1. Socle commun avec DASF-V

Repris **à l'identique** :

| Élément | Référence |
|---|---|
| Architecture en ports (`RadioPort`, `CryptoPort`, `SensorPort`, `Clock`), cœur Kotlin en `commonMain` | [DASF §1] |
| Identités `IK`/`XK`, QR ami, époques, key blinding, `NID_e`, mode certifié optionnel | [DASF §2] |
| Format du bundle (sans le flag `mule_replicated`), chiffrement de bout en bout, SOS | [DASF §3.1] |
| ACK signé et purge vérifiable | [DASF §3.2, §8] |
| BeaconShort / BeaconFull, fraîcheur, `nbr_bloom` | [DASF §3.3, §5.1–5.2] |
| COMMIT et jetons incertains | [DASF §6.3] |
| Politique batterie, évacuation | [DASF §10] |
| Congestion (advertising, Trickle, scan, rate-limits) | [DASF §11] |
| Plausibilité des beacons, réputation | [DASF §12] |

Ce qui **change** : le calcul d'utilité (PRoPHET et mules remplacés par communautés + centralités) et la décision de routage.

---

## 2. Notions sociales

| Notion | Définition |
|---|---|
| **Durée de contact cumulée** `dur[v]` | temps total passé à portée de `v` pendant l'époque |
| **Ensemble familier** `F` | nœuds avec `dur[v] ≥ T_FAM` (20 min) |
| **Communauté** `C` | `{moi} ∪ amis (QR) ∪` nœuds ajoutés par SIMPLE (§4) |
| **Rang global** `GR` | nombre moyen de nœuds distincts rencontrés par fenêtre (C-Window, §5) |
| **Rang local** `LR` | idem, en ne comptant que les membres de `C` |
| **Dans la bulle de d** | `d ∈ C` |

Une « rencontre » compte si le voisin a été entendu pendant au moins `T_MEET = 30 s` cumulées dans la fenêtre.

---

## 3. État local

```kotlin
class SocialState(
  val contactDur: MutableMap<Nid, Long>,   // durée cumulée par voisin (époque)
  val familiar: MutableSet<Nid>,           // F
  val community: MutableSet<Nid>,          // C (explicite, ≤ C_MAX)
  val friends: Set<IkPub>,                 // amis QR (permanents)
  val windows: ArrayDeque<WindowCount>,    // C-Window : 4 fenêtres de 30 min
  var globalRank: Int,                     // 0..255
  var localRank: Int,                      // 0..255
  val rankSamples: RunningMedian           // médiane des rangs observés chez les pairs
)

class WindowCount(
  val start: Long,
  val met: MutableSet<Nid>,                // nœuds distincts rencontrés
  val metInC: MutableSet<Nid>              // sous-ensemble dans C
)

class Holding(                             // message dans le buffer
  val bundle: Bundle,
  var tokens: Int,
  var uncertainTokens: Int, var uncertainSince: Long?,
  val receivedAt: Long,
  var lastProgressAt: Long,                // dernier transfert réussi
  var stuckReplicated: Boolean
)

class PeerSocial(                          // reçu en session
  val globalRank: Int, val localRank: Int,
  val familiarSize: Int, val familiarBloom: Bloom,   // 512 bits, k = 3
  val communitySize: Int, val communityBloom: Bloom  // 1024 bits, k = 4
)
```

**Représentation compacte échangée :**

| Élément | Taille |
|---|---|
| `globalRank`, `localRank` | 2 o |
| `familiarSize` + `familiarBloom` (512 bits, k = 3) | 2 + 64 o |
| `communitySize` + `communityBloom` (1024 bits, k = 4) | 2 + 128 o |
| **Total** | **≈ 198 o** |

Taux de faux positifs du `communityBloom` pour 150 membres : ~4 %.

---

## 4. Détection de communauté (SIMPLE adapté)

Inspiré de l'algorithme distribué SIMPLE (Hui et al., 2007).

### 4.1 Initialisation (et à chaque époque)

```
C ← {moi} ∪ { NID_e(ami) pour chaque ami QR }
F ← ∅
```

Le `NID_e` d'un ami est calculable hors ligne grâce à son `IK_pub` [DASF §2.3].

### 4.2 À chaque rencontre avec v

```kotlin
fun onSocialExchange(v: Nid, p: PeerSocial, contactMs: Long) {
  contactDur[v] = (contactDur[v] ?: 0) + contactMs

  // 1. ensemble familier
  if (v !in familiar && contactDur[v]!! >= T_FAM) {
    familiar += v
    addToCommunity(v)                                  // un familier entre dans C
  }

  // 2. ajout par recouvrement : v partage assez de familiers avec ma communauté
  if (v !in community && p.familiarSize > 0) {
    val inter = community.count { p.familiarBloom.mightContain(it) }   // |F_v ∩ C| estimé
    if (inter.toDouble() / p.familiarSize >= LAMBDA) addToCommunity(v)
  }

  // 3. fusion de communautés
  if (v in community && p.communitySize > 0) {
    val inter = community.count { p.communityBloom.mightContain(it) }  // |C_v ∩ C| estimé
    val union = p.communitySize + community.size - inter
    if (inter >= GAMMA * union) requestMerge(v)        // MERGE_REQ en session (§6)
  }
}

fun addToCommunity(v: Nid) { if (community.size < C_MAX) community += v }
```

- Les intersections sont **estimées** en testant mes membres explicites contre le Bloom de v (les faux positifs surestiment légèrement).
- `MERGE_REQ` : v envoie sa liste **explicite** de membres (≤ `C_MAX` × 8 o ≈ 2,4 Ko), uniquement si la condition est remplie. On ajoute jusqu'à `C_MAX`, en priorité les membres que je connais déjà comme familiers.

---

## 5. Centralités (C-Window)

Fenêtres glissantes de `W = 30 min`, on garde les `N_W = 4` dernières (2 h).

```kotlin
fun onMeet(v: Nid) {            // appelé quand v atteint T_MEET dans la fenêtre courante
  current.met += v
  if (v in community) current.metInC += v
}

fun recomputeRanks() {          // à chaque fin de fenêtre, et toutes les 5 min (fenêtre partielle pondérée)
  globalRank = min(255, windows.map { it.met.size }.average().roundToInt())
  localRank  = min(255, windows.map { it.metInC.size }.average().roundToInt())
}
```

Les rangs sont des **comptes de pseudonymes** : ils restent valables à travers les changements d'époque.

---

## 6. Session

Même déroulé que [DASF §6.2], l'étape `UTIL_REQ` étant remplacée par `SOCIAL` :

```
1. HELLO      BeaconFull (+ Cred_e au 1er contact de l'époque) → vérifs
2. ACK_SYNC   échange des ACK manquants
3. PURGE      suppression des messages acquittés (signature vérifiée)
4. SUMMARY    liste exacte des msg_id tronqués (8 o)
5. SOCIAL     échange PeerSocial (~198 o) → onSocialExchange()
6. MERGE_REQ  (si condition de fusion) liste explicite des membres
7. TRANSFER   file triée (§7), COMMIT par bundle
8. CLOSE      mise à jour des fenêtres, réputation, cooldown
```

**Choix des pairs** ([DASF §6.1] adapté) :

```
score(B) = 10 · [j'ai un message pour B]
         +  5 · [j'ai un message pour un NID dans B.nbr_bloom]
         +  4 · [B est dans une bulle de destination de mes messages]   (après 1er échange)
         +  2 · [B.globalRank > mon globalRank]
         +  1 · [B.rssiSlope ≥ 0]
         −  5 · [B.rssiSlope < −SLOPE_LEAVING]
```

Le critère « bulle » n'est connu qu'après un premier échange `SOCIAL` avec B : on le met en cache pour l'époque.

---

## 7. Décision de routage

### 7.1 Budget de copies

```
L = L_base(prio)       normal 8, SOS 16   (fixe, pour une comparaison propre)
k_min                  normal 2, SOS 4    (jamais descendre sous k_min porteurs volontairement)
```

### 7.2 File de transfert de A vers B

```kotlin
fun planTransfers(A: Node, B: PeerView): List<Transfer> {
  val out = mutableListOf<Transfer>()
  val gB = min(B.globalRank, rankCap(B))
  val lB = min(B.localRank,  rankCap(B))
  for (h in A.buffer.filter { it.bundle.msgId !in B.summary }) {
    val d   = h.bundle.destNid
    val aIn = d in A.community
    val bIn = B.communityBloom.mightContain(d)
    when {
      // 1. livraison directe
      d == B.nid ->
        out += Transfer(h, tokens = h.tokens, move = true, rank = 1)

      // 2. relais à 2 sauts (repris de DASF-V)
      B.nbrBloomFresh() && d in B.nbrBloom && B.rssiSlope >= -SLOPE_LEAVING ->
        out += Transfer(h, 1, move = (h.tokens == 1), rank = 2)

      // 3. A est déjà dans la bulle : ne transmettre qu'à un membre plus central localement
      aIn ->
        if (bIn && lB > A.localRank + DELTA_L) out += forward(h, rank = 3)

      // 4. B est dans la bulle et pas A : entrer dans la bulle
      bIn ->
        out += forward(h, rank = 3)

      // 5. hors bulle : monter en centralité globale
      gB > A.globalRank + DELTA_G ->
        out += forward(h, rank = 4)

      // 6. message bloqué : une réplication de diversification
      stuck(h) && !h.stuckReplicated && B.nid !in A.community ->
        out += Transfer(h, 1, move = false, replicate = true, rank = 5)
    }
  }
  return out.sortedWith(compareBy({ it.rank }, { it.h.ttlRemaining() }))
}

fun forward(h: Holding, rank: Int) =
  if (h.tokens > 1) Transfer(h, h.tokens / 2, move = false, rank = rank)   // division binaire
  else              Transfer(h, 1, move = true, rank = rank)               // déplacement avec COMMIT

fun stuck(h: Holding) =
  h.tokens == 1 && now() - h.lastProgressAt > T_STUCK
```

### 7.3 Règles

- `move = true` : A supprime sa copie **après** COMMIT.
- `move = false` : A retranche les jetons donnés **après** COMMIT ; `lastProgressAt` est mis à jour.
- `replicate` : A garde son jeton ; la copie de B porte `stuckReplicated = true` ; A marque aussi sa copie → une seule réplication par copie, total ≤ 2L.
- **Priorité SOS** : pour un SOS, les règles 3 à 5 s'appliquent avec `DELTA_L = DELTA_G = 0`.
- **Asymétrie assumée** : « A dans la bulle de d » se lit dans la communauté de A, « B dans la bulle » dans le Bloom de B. Les deux vues peuvent diverger ; c'est sans conséquence grave (au pire un transfert de plus ou de moins).

---

## 8. Anti-blocage et anti-blackhole

### 8.1 Blocage au sommet

Problème connu de BUBBLE Rap : le message atteint un nœud très central qui ne croise jamais la bulle du destinataire. Réponses :

- **Réplication de diversification** (règle 6) après `T_STUCK = 30 min` sans progrès.
- **Relais à 2 sauts** (règle 2) pour court-circuiter la hiérarchie quand le destinataire est proche.

### 8.2 Rangs falsifiés

Les rangs sont auto-déclarés : un attaquant qui annonce 255 aspire tous les messages hors bulle.

```
rankCap(B) =
  si B vu depuis < 5 min, sans credential, réputation inconnue :
      max(médiane des rangs observés chez mes pairs, 1) × 1,5
  sinon :
      255
```

- Plausibilité : rejeter un `globalRank` > 3 × la plus forte densité locale que j'ai mesurée sur les 2 dernières heures (on ne peut pas rencontrer beaucoup plus de monde que ce qui passe à portée).
- Réputation [DASF §12.2] : un nœud qui reçoit beaucoup de messages sans jamais produire d'ACK observable est ignoré pour l'époque.

### 8.3 Bloom de communauté falsifié

Un Bloom rempli à 100 % fait croire que B est dans toutes les bulles. Rejeter si le remplissage du `communityBloom` dépasse la valeur attendue pour `communitySize` de plus de 20 %, ou si `communitySize > C_MAX`.

---

## 9. Buffer et charge des nœuds centraux

Les nœuds centraux reçoivent mécaniquement beaucoup de messages.

- **Capacité :** 500 bundles.
- **Admission :** si buffer > 80 %, n'accepter que les messages pour lesquels je suis **dans la bulle** (`d ∈ C`) ou les SOS.
- **Entrée par pair :** ≤ 50 bundles / min [DASF §11].
- **Ordre de suppression :**
  1. acquittés ;
  2. expirés ;
  3. messages hors bulle, par `tokens` croissant puis du plus ancien au plus récent ;
  4. messages dans la bulle, même ordre ;
  5. SOS en dernier.

---

## 10. Changement d'époque

À chaque changement d'époque [DASF §13] :

1. `C ← {moi} ∪ NID_{e+1}(amis)` : les amis sont conservés (recalculables), les autres membres sont perdus (non reliables).
2. `F ← ∅`, `contactDur ← ∅`.
3. Rangs (`windows`) **conservés** : ce sont des comptes, pas des identités.
4. Buffer conservé ; période de grâce de 2 h pour `NID_e`.

La communauté se reconstruit en quelques dizaines de minutes à partir des familiers.

---

## 11. Paramètres

| Paramètre | Défaut | À régler ? |
|---|---|---|
| `L_base` normal / SOS | 8 / 16 | **oui** |
| `k_min` normal / SOS | 2 / 4 | oui |
| `T_MEET` | 30 s | oui |
| `T_FAM` | 20 min | **oui** |
| `LAMBDA` (ajout) | 0,6 | **oui** |
| `GAMMA` (fusion) | 0,6 | **oui** |
| `C_MAX` | 300 | non |
| `W` / `N_W` (C-Window) | 30 min / 4 | oui |
| `DELTA_G` / `DELTA_L` | 2 / 1 | **oui** |
| `T_STUCK` | 30 min | oui |
| Bloom familier / communauté | 512 bits k=3 / 1024 bits k=4 | non |
| Facteur `rankCap` | 1,5 × médiane | oui |
| Buffer / seuil d'admission | 500 / 80 % | non |
| TTL normal / SOS | 4 h / 12 h | non |

---

## 12. Plan d'implémentation et évaluation

### 12.1 Ordre

1. Réutiliser le simulateur et le socle DASF-V (ports, buffer, session, COMMIT, ACK).
2. `SocialState` : fenêtres C-Window et rangs.
3. Communauté : amorçage par le graphe d'amis, puis SIMPLE (ajout, fusion, `MERGE_REQ`).
4. `planTransfers` (règles 1 à 5), puis règle 6 (anti-blocage).
5. Protections : `rankCap`, plausibilité des Bloom, admission des nœuds centraux.
6. Changement d'époque.

### 12.2 Modèle de simulation spécifique

Le graphe d'amis est une **entrée critique** : il faut le générer explicitement.

- Groupes d'amis de 2 à 8 personnes (loi à choisir), qui se déplacent ensemble avec une probabilité de séparation temporaire.
- Proportion d'utilisateurs **sans ami dans l'app** : 0 / 20 / 50 %.
- Une partie des messages envoyés **hors du groupe** (ex. 20 %) pour tester la traversée entre bulles.

### 12.3 Métriques

Identiques à [DASF §15.2], plus :

- **qualité des communautés** détectées vs groupes réels (ex. indice de Jaccard moyen) ;
- **charge des nœuds centraux** : distribution des bundles relayés par nœud (percentiles 50 / 90 / 99) ;
- **taux de messages bloqués** (règle 6 déclenchée).

### 12.4 Ablation

Sans amorçage par les amis, sans SIMPLE (amis seuls), sans relais 2 sauts, sans règle 6, rangs non plafonnés.

---

## 13. Limites connues

| Limite | Effet | Piste |
|---|---|---|
| **Fuite du graphe social** : le `communityBloom` permet à tout pair de tester si un `NID` est dans ma communauté | Reconstruction partielle du graphe social (pseudonyme, par époque) | Échanger le Bloom seulement avec les pairs vérifiés ; mode « requête » (je ne réponds que pour les destinations de messages présentés) avec réponse bruitée |
| **Charge concentrée** sur les nœuds centraux | Batterie et buffer saturés chez quelques-uns | Admission §9, politique batterie, plafonds |
| **Rangs auto-déclarés** | Porte d'entrée pour un blackhole | `rankCap`, plausibilité, réputation, mode certifié |
| **Destinataires isolés** (sans amis dans l'app) | Bulle quasi vide, routage uniquement par rang global | Relais 2 sauts, règle 6 |
| **Perte des membres non-amis à chaque époque** | Communauté appauvrie pendant la reconstruction | Époques longues, calées sur une heure creuse |
| **Dépendance au modèle de groupes** en simulation | Résultats sensibles à la génération du graphe d'amis | Varier taille des groupes et taux d'adoption |
