# Bitchat — Spécification

Chemin des messages privés de bitchat, réduit au niveau réseau : inondation dirigée, outbox de la source et couriers spray-and-wait.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/bitchat.py` (`--routing bitchat`), 12 tests dans `tests/test_routing_bitchat.py`. Spec rédigée à partir du code de l'application iOS `permissionlesstech/bitchat` (commit `5e9287f`, septembre 2026). Les paramètres par défaut sont ses constantes. Fiche courte : `docs/algorithmes/bitchat.md`.

---

## 1. Principe

`BitchatRouting` hérite de `ManagedFloodRouting` (voir `MANAGED-FLOOD.md`) pour le cache de messages et les ACK inondés. Chaque copie porte un rôle dans `routing_state["role"]` :

| Rôle | Qui | Comportement |
|---|---|---|
| `source` | l'émetteur | outbox : inonde quand la destination est joignable, dépose chez des couriers |
| `flood` | un relais | relaie pendant `relay_window_s`, puis spool ou oubli |
| `courier` | un porteur | garde la copie, en donne la moitié, relance une inondation |

---

## 2. Spécification

### 2.1 Maillage (`RelayController`, `BLEService`)

- Une copie `flood` reçue au tick `t` est relayée au tick suivant (`relay_window_s = 1 s`, le jitter de 20 à 60 ms est sous le tick) à tout voisin qui ne l'a ni en buffer, ni en cache, ni acquittée.
- TTL : 7 sauts depuis l'origine de l'inondation (`base`), sans plafond selon le degré (messages privés).
- Si la destination est voisine directe du porteur, il n'envoie qu'à elle (le moteur livre) : `IGNORE` pour les autres.
- Dédup : cache de 1000 entrées par nœud, une entrée expire après 300 s.
- **Spool** : à la fin de la fenêtre, un relais qui n'a eu aucun voisin autre que celui d'arrivée garde le paquet 60 s (512 au plus, éviction FIFO). Toutes les 5 s, s'il a un voisin autre que celui d'arrivée, il rediffuse pendant un tick puis l'oublie.

### 2.2 Outbox de la source (`MessageRouter`)

- **Joignabilité** : toutes les 4 s, l'annonce de la destination est propagée sur le graphe des voisins du tick : TTL 7, un relais à 2 voisins ou moins garde le TTL reçu, à 6 voisins ou plus le ramène à 5, sinon à 7 (minimum 2), puis décrémente. La source est joignable si l'annonce l'atteint ; elle le reste 60 s.
- **Envoi** : à la création si joignable, puis à chaque passage injoignable → joignable. Chaque envoi est une nouvelle inondation (`attempt` + 1). Au-delà de 8 envois, le message est abandonné.
- Le message reste chez la source jusqu'à l'ACK ou son expiration (`message_ttl_s` ; les 24 h de bitchat ne sont jamais atteintes).

### 2.3 Couriers (`CourierStore`)

- **Dépôt** : hors inondation en cours, la source confie une copie (`copies = 4`) à tout voisin mobile éligible, 3 couriers distincts au plus par message. Un ami réciproque (`friends`) passe avant un non-ami présent au même moment.
- **Quotas** du courier, sinon refus : 40 enveloppes, dont 20 de non-amis ; 5 par ami déposant, 2 par non-ami.
- **Spray** : un courier avec `copies > 1` donne `copies // 2` à un voisin qui ne lui a pas donné l'enveloppe, à qui il n'en a pas déjà donné, et qui l'accepte (mêmes quotas).
- **Remise directe** : au contact de la destination, par la livraison directe du moteur.
- **Remise à distance** : si l'annonce de la destination atteint le courier, il lance une inondation (nouvelle `attempt`, TTL 7 depuis lui), au plus toutes les 600 s.

### 2.4 ACK

Ceux de `managed_flood` : la livraison crée un ACK inondé (TTL 7, un saut par tick) qui purge les copies des nœuds qu'il atteint. Une source qui le reçoit ferme son outbox.

---

## 3. Paramètres

| Paramètre | Défaut | Constante bitchat |
|---|---|---|
| `ttl` | 7 | `messageTTLDefault` |
| `relay_window_s` | 1 s | jitter 20–60 ms (un tick) |
| `cache_size` | 1000 | `messageDedupMaxCount` |
| `dedup_max_age_s` | 300 s | `messageDedupMaxAgeSeconds` |
| `spool_window_s` | 60 s | `bleDirectedSpoolWindowSeconds` |
| `spool_capacity` | 512 | `bleDirectedSpoolCapacity` |
| `maintenance_interval_s` | 5 s | `bleMaintenanceInterval` |
| `announce_interval_s` | 4 s | `bleAnnounceIntervalSeconds` |
| `announce_ttl` / `dense_announce_ttl` | 7 / 5 | `RelayController` |
| `high_degree_threshold` | 6 | `bleHighDegreeThreshold` |
| `reachability_retention_s` | 60 s | `bleReachabilityRetentionVerifiedSeconds` |
| `max_send_attempts` | 8 | `MessageRouter.maxSendAttempts` |
| `max_couriers_per_message` | 3 | `MessageRouter.maxCouriersPerMessage` |
| `courier_initial_copies` | 4 | `courierInitialCopies` |
| `courier_handover_cooldown_s` | 600 s | `courierRemoteHandoverCooldownSeconds` |
| `courier_capacity` / `courier_verified_capacity` | 40 / 20 | `CourierStore.Limits` |
| `courier_per_favorite_depositor` / `courier_per_verified_depositor` | 5 / 2 | `CourierStore.Limits` |

---

## 4. Écarts avec bitchat

| bitchat | Simulateur |
|---|---|
| Jitter 10–220 ms, annulation d'un relais programmé sur doublon | Relais au tick suivant |
| Annonces réelles, perdues ou non | Joignabilité calculée sur le graphe des voisins, sans perte |
| Favoris mutuels, pairs « vérifiés » (annonce signée) | Amis réciproques du graphe social ; tout autre pair mobile est « vérifié » |
| ACK de livraison = message privé vers l'émetteur | ACK inondés de `managed_flood`, qui purgent aussi les copies |
| Courier plein : éviction des plus anciens, non-amis d'abord | Refus du dépôt |
| Routage par source, passerelles Nostr, Noise, fragmentation | Non modélisés |
| TTL repart à 7 à chaque remise à distance | Idem pour `ttl`, mais le TTL du moteur (`message_ttl_hops`, 8) compte les sauts de bout en bout |

---

## 5. Points d'attention

- Les bornes relaient mais ne sont jamais couriers : leur backhaul dupliquerait le budget de copies.
- `max_source_retransmissions` de `managed_flood` est forcé à 0 : l'outbox remplace ses réémissions.
- Le hook `_relay_window_over` de `ManagedFloodRouting` est le point d'extension du spool ; `managed_flood` seul est inchangé.
