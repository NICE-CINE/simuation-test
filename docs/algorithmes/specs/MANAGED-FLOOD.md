# Managed Flood — Spécification

Inondation gérée de la couche réseau Bluetooth Mesh, sans stockage-transport, avec un mode acquitté de bout en bout.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/managed_flood.py` (`--routing managed_flood`), 14 tests dans `tests/test_routing_managed_flood.py`. Spec rédigée a posteriori à partir du code : elle décrit l'implémentation, pas un document d'origine. Fiche courte : `docs/algorithmes/managed_flood.md`.

---

## 1. Principe

Un nœud ne relaie un PDU que pendant une courte fenêtre après l'avoir reçu, puis l'oublie. Trois mécanismes bornent l'inondation : le TTL en sauts, un cache de messages par nœud qui rejette tout PDU déjà vu, et la fenêtre de relais. Il n'y a pas de stockage-transport : si le destinataire n'est pas joignable pendant la fenêtre, le PDU est perdu, sauf réémission par la source.

C'est la référence « réseau connexe » face aux algorithmes DTN.

---

## 2. Référence

Bluetooth SIG, *Mesh Profile Specification* 1.0 (2017), couche réseau : relais (*Relay feature*), TTL, cache de messages réseau. Le mode acquitté reprend l'idée des messages acquittés de la couche d'accès (requête, réponse *Status*, réémission par le client sans réponse).

---

## 3. Spécification

### 3.1 Identité d'un PDU

Un PDU est identifié par `(msg_id, SEQ)`. Le SEQ est modélisé par `routing_state["attempt"]` (0 pour l'émission initiale). Une réémission de la source porte un nouveau SEQ : les caches la traitent comme un nouveau PDU.

### 3.2 État (global, partagé)

| État | Contenu |
|---|---|
| Cache de messages | par nœud : `(msg_id, SEQ)` → instant de première réception ; FIFO, taille `cache_size` |
| ACK connus | par nœud : ensemble des `msg_id` acquittés ; FIFO, taille `cache_size` |
| ACK en relais | `(nœud, msg_id, sauts, appris à)` encore dans leur fenêtre |
| En attente d'ACK | `msg_id` → (source, PDU, instant d'émission) |

### 3.3 Fenêtre de relais (`refresh`)

Appliquée au porteur à chaque `decide`, et à tous les nœuds à chaque tick :

```
si le porteur connaît l'ACK de m            → retirer m du buffer ; pas de relais
première_réception = cache (enregistrée maintenant si absente)
si maintenant − première_réception ≤ fenêtre → peut relayer
sinon                                        → retirer m du buffer ;
                                               si mode acquitté et porteur = source → m passe en attente d'ACK
```

### 3.4 Décision

Pour chaque message `m` du porteur `A`, à chaque contact avec `B` :

```
si refresh(A, m) interdit le relais                   → IGNORE
si m.hops ≥ ttl                                       → IGNORE
si B détient m, a (msg_id, SEQ) en cache, ou connaît l'ACK → IGNORE
sinon                                                 → FORWARD ; (msg_id, SEQ) entre dans le cache de B
```

### 3.5 Mode acquitté

- **ACK** : à la livraison, le destinataire connaît l'ACK (saut 0), puis le porteur qui vient de livrer (saut 1).
- **Propagation** : à chaque tick, tout nœud qui connaît un ACK depuis moins de `relay_window_s`, à moins de `ttl` sauts, le transmet à ses voisins actifs. Un ACK appris pendant un tick n'est relayé qu'à partir du tick suivant.
- **Purge** : un nœud qui apprend un ACK retire le message de son buffer.
- **Coût** : chaque saut d'ACK coûte l'énergie tx/rx de `ack_size_bytes`, mais pas de bande passante.
- **Réémission** : sans ACK `ack_timeout_s` après l'émission, la source réémet le PDU avec `SEQ + 1`, au plus `max_source_retransmissions` fois, si elle est active et que le message n'a pas expiré.

### 3.6 Buffer

FIFO du moteur, rarement sollicité : un PDU ne reste que `relay_window_s` dans un buffer.

---

## 4. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `ttl` | 7 | sauts maximum, PDU et ACK |
| `relay_window_s` | 3 s | durée pendant laquelle un nœud relaie un PDU ou un ACK |
| `cache_size` | 256 | taille du cache de messages et de la table d'ACK, par nœud |
| `acknowledged` | `True` | ACK de bout en bout et réémission par la source |
| `ack_timeout_s` | 30 s | délai avant réémission |
| `max_source_retransmissions` | 2 | réémissions maximum |
| `ack_size_bytes` | 16 o | taille facturée pour chaque saut d'ACK |
| `energy` | `EnergyConfig()` | modèle d'énergie pour le coût des ACK |

---

## 5. Implémentation dans le simulateur

- Hooks : `on_simulation_start` (dictionnaire des nœuds, nécessaire pour vider les buffers dans `on_tick`), `decide`, `on_forward`, `on_delivered`, `on_tick`.
- L'algorithme retire lui-même les PDU des buffers (`node.buffer.pop`), y compris dans `on_tick`.
- **Balayage par tick** : sans lui, un nœud isolé garderait un PDU expiré jusqu'à son prochain contact, et la livraison directe du moteur (qui n'appelle pas `decide`) en ferait du stockage-transport.
- Le TTL de l'algorithme (7) s'ajoute à celui du moteur (8) : c'est le plus petit qui s'applique au relais.

---

## 6. Écarts avec Bluetooth Mesh

| Bluetooth Mesh | Simulateur |
|---|---|
| Relais avec un nombre de retransmissions et un intervalle | Fenêtre de relais en secondes, une transmission par voisin et par contact |
| TTL décrémenté ; un PDU à TTL ≤ 1 n'est pas relayé | Compteur de sauts du moteur comparé à `ttl` ; la livraison directe reste possible au-delà (règle commune à tous les algorithmes) |
| Chiffrement réseau, IV index, SEQ sur 24 bits | Non modélisés ; SEQ = numéro de tentative |
| Nœuds *Friend* / *Low Power*, proxy GATT | Non modélisés |
| ACK de la couche d'accès, transportés comme des messages | ACK hors bande : énergie facturée, temps d'antenne ignoré |

---

## 7. Points d'attention

- **Pas de stockage-transport** : en festival clairsemé, la livraison chute nettement face aux algorithmes DTN. C'est attendu.
- **Réémissions** : elles ne rattrapent que des coupures courtes (`ack_timeout_s × max_source_retransmissions`, soit 60 s par défaut).
- **Cache borné** : sous forte charge, un PDU oublié par le cache peut repasser.
- **ACK gratuits en bande passante** : le budget de lien du moteur ne les voit pas.
