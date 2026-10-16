# Mesures radio et réglages du simulateur

> **Statut** : valeurs recalées le 16 oct. 2026 sur le banc radio de terrain
> de l'app Nice (Google Nearby Connections, `P2P_CLUSTER`). Chaque paramètre
> indique s'il est **mesuré**, **calculé** ou **estimé**.
> Code : `BleConfig` et `RadioParams` (`src/festival_ble_sim/config.py`),
> modèle de propagation dans `radio.py`, pertes et débit dans `network.py`.
> L'énergie a sa propre page : `docs/energie/consommation.md`.

## 1. D'où viennent les chiffres

L'outil de mesure tourne dans l'app (dépôt de l'app,
`app/android/app/src/main/kotlin/com/nice/app/bench/`). Les données brutes
(CSV et `NOTES.md` de chaque passe) sont dans le dépôt de l'app, sous
`bench-data/2026-10-16-champ-libre/` et `bench-data/2026-10-16-passes-2-3/`.

- **Ancre** : un Galaxy A56 (Samsung) fixe, posé à plat écran vers le haut.
  Il émet une balise BLE (pour le RSSI), un ping numéroté par seconde de
  1 650 o (la taille d'un vrai message) et un flux de 256 Kio toutes les 20 s.
- **Marcheur** : un Honor 8X tenu devant soi, qui s'arrête 60 s à chaque
  repère (1, 5, 10, 20, 30, 50 m, puis plus loin).
- **Lieu** : campus Leprince-Ringuet, pelouse et parking en plein air,
  passants occasionnels, Wi-Fi coupé.
- **Mesure à la réception** : côté émetteur, Nearby annonce 256 Kio
  « envoyés » en 75 ms alors que le récepteur met 2 à 5 s à les recevoir.

| Passe | Orientation de l'ancre | Conditions |
| --- | --- | --- |
| Libre n°1 | port de charge vers le marcheur | repères jusqu'à 50 m, puis jusqu'à ~150 m |
| Foule | côté droit vers le marcheur, sens de marche inversé | **5 personnes debout devant l'ancre** (à ~1 m), arrêtée à 75 m |
| Libre n°2 | comme la passe foule | repères jusqu'à « 150 m », en réalité ~125 m |

Pertes de pings et débit à la réception (Mbit/s) :

| Distance | Libre n°1 | Libre n°2 | Foule |
| --- | --- | --- | --- |
| 1 m | 0 % / 0,54 | 0 % / 0,37 | 0 % / 0,25 |
| 5 m | 0 % / 0,56 | 0 % / 0,42 | 0 % / 0,22 |
| 10 m | 0 % / 0,52 | 0 % / 0,31 | 5 % / 0,25 |
| 20 m | 0 % / 0,33 | 0 % / 0,25 | 0 % / 0,17 |
| 30 m | 8 % / 0,30 | 38 % (coupure) / 0,27 | 90 % (coupure) |
| 50 m | 0 % / 0,23 | 0 % / 0,14 | 97 % |
| 75 m | — | 32 % / 0,10 | 100 % → arrêt |
| 100 m | — | 63 % / 0,16 | |
| ~125 m | — | 90 % | |
| Fin du lien | jamais déclarée, plus rien au-delà de ~150 m | ~150 m | ~30 m |

RSSI médian de la balise BLE (dBm) :

| Distance | Libre n°1 | Libre n°2 | Foule |
| --- | --- | --- | --- |
| 1 m | −64 | −75 | −94 |
| 5 m | −77 | −83 | −91 |
| 10 m | −82 | −94 | −96 |
| 20 m | −88 | −94 | — |
| 30 m | −92 | −92 | — |
| 50 m | −93 | — | — |

Le RSSI n'est pas fiable avec peu de relevés : au-delà de 50 m pour la
passe n°1, au-delà de 10 m pour la passe n°2 et la passe foule.

**Limites** : une passe par condition, deux modèles de téléphone, des
passants de temps en temps, deux téléphones seulement (rien sur 3 voisins ou
plus).

## 2. Portée et affaiblissement

Le modèle est log-distance (`radio.py`) : la puissance reçue perd
`10 × path_loss_exponent` dB par décade de distance, et le lien existe tant
qu'elle reste au-dessus de la sensibilité. Seuls l'écart puissance −
sensibilité et l'exposant comptent : la puissance (`tx_power_dbm`) est une
puissance *effective* (antenne, main, corps compris), pas celle de la puce.

Ce que disent les mesures :

- **Plein air** (passe n°1) : RSSI ≈ −64 − 18·log₁₀(d), soit un exposant
  d'environ **1,8**. Portée utile ~**50 m**, dernier recours jusqu'à
  100–150 m.
- **5 personnes devant l'ancre** : la portée tombe à ~**30 m** et le débit
  est divisé par ~2, même de près. Sur le RSSI de la balise, ces corps
  coûtent 20 à 30 dB, mais il était au plancher avec peu de relevés ; sur la
  portée du lien Nearby, l'écart (50 → 30 m) ne vaut que ~4 dB. Le
  simulateur suit la portée du lien, c'est ce qu'il utilise.
- **Variabilité** : ~11 dB d'écart à 1 m entre les passes n°1 et n°2, qui
  ne diffèrent que par l'orientation de l'ancre (90°) et le sens de marche.

**Pourquoi le simulateur garde 30 m et l'exposant 2,7.** La passe « foule »
n'est pas une foule de festival : 5 personnes groupées devant un téléphone,
dont la perte est la même à 5 m qu'à 30 m. Sur un site à 3 m² par personne,
un lien de 30 m traverse des dizaines de corps répartis sur tout le trajet,
et la perte croît avec la distance, c'est-à-dire un exposant plus fort que
celui du plein air. Les 30 m mesurés sont donc une **borne haute** pour un
festival ; la vraie portée en foule est inconnue.

| Paramètre | Valeur | Dérivation | Statut |
| --- | --- | --- | --- |
| portée téléphone (`radio.max_range_m`) | **30 m** | `tx_power_dbm=-10`, `reference_loss_db=40`, `receiver_sensitivity_dbm=-90`, exposant 2,7 | **mesurée** avec 5 personnes devant l'ancre, borne haute pour une foule |
| `path_loss_exponent` | **2,7** | corps répartis sur le trajet en foule | **estimé** (plein air mesuré : 1,8) |
| portée borne (`beacon_radio`) | **60 m** | 2 × la portée téléphone, `tx_power_dbm=-2` | **choisi**, non mesuré |
| `shadowing_std_db` | **4 dB** | littérature BLE en intérieur et en foule | **estimé** ; le banc voit ~11 dB entre passes, mais c'est un effet lent (orientation, terrain), qu'un tirage indépendant à chaque tick ne reproduit pas |

### Recettes

- **Plein air** (passe n°1, ~50 m) :
  `--set ble.phone_radio.path_loss_exponent=1.8 --phone-tx-power -19.4`.
  Les bornes ne sont pas ajustées.
- **Foule plus dense que la mesure** : la vraie portée en festival étant
  inconnue, comparer aussi les algorithmes à 20 m (`--phone-tx-power -15`)
  et 15 m (`--phone-tx-power -18`).

## 3. Débit

Le débit est **global à chaque téléphone** (partagé par toutes ses
connexions), pas propre à chaque lien. La règle « débit ÷ n » avec plusieurs
voisins vient de la documentation de Nearby, pas d'une mesure.

| Paramètre | Ancienne valeur | Nouvelle valeur | Dérivation | Statut |
| --- | --- | --- | --- | --- |
| `transfer_rate_bytes_per_s` | 37 000 (banc à moins d'1 m, 12 oct.) | **31 000** | 0,25 Mbit/s de 1 à 10 m avec 5 personnes devant l'ancre (plein air : 0,37 à 0,54 Mbit/s, soit 46 à 68 ko/s) | **mesuré**, sans doute optimiste pour une vraie foule |
| `signal_margin_cutoff_db` | 6 dB | **10 dB** | calé sur la baisse du débit avec la distance (ci-dessous) | **ajusté** sur une passe par condition |
| `weak_signal_max_probability` | 0,30 | **0,60** | idem | **ajusté** |

Les autres téléphones qui émettent (la charge du canal) font encore baisser
ce débit dans le simulateur : ce sont les collisions et retransmissions de
`network.py`. Les 5 personnes du banc n'avaient pas l'app : leur effet est
celui des corps, d'où la baisse de `transfer_rate_bytes_per_s`, sans double
compte avec les collisions.

**Baisse avec la distance.** Près du bord de portée, une part p des paquets
est renvoyée (perte « signal faible », de 0 à la marge
`signal_margin_cutoff_db` jusqu'à `weak_signal_max_probability` à la
sensibilité), ce qui coûte 1/(1−p) fois le temps d'antenne. Débit utile
moyen simulé (hasard de 4 dB compris, coupures comptées à 0), rapporté au
débit de près, contre le mesuré :

| Distance | Simulé, réglage par défaut | Mesuré, 5 personnes | Simulé, plein air | Mesuré, plein air (passes 1 / 2) |
| --- | --- | --- | --- | --- |
| 10 m | 0,96 | 1,0 | 0,95 | 0,95 / 0,78 |
| 20 m | 0,64 | 0,7 | 0,78 | 0,6 / 0,63 |
| 30 m | 0,30 | coupure (90 % de pertes) | 0,59 | 0,55 / 0,68 |
| 50 m | hors portée | 97 % de pertes | 0,30 | 0,42 / 0,35 |

## 4. Connexion et coupures

- **Reconnexion** : pendant la passe libre n°2 et la passe foule, quand le
  marcheur revient à portée après une coupure, Nearby se reconnecte en
  ~**12 s** ; plus loin (vers 100 m, ou pendant la passe foule) en 26 à
  80 s. Les heures exactes sont dans `samsung_anchor.csv`. Au banc, à moins
  d'un mètre, la découverte puis la connexion prenaient ~7 s, et un essai de
  reconnexion au bureau a donné 1 réussite en 1,4 s et 2 échecs à 60 s (dus
  au Bluetooth du Honor).
- **Lien fantôme** : pendant la passe n°1, hors de portée, Nearby n'a
  **jamais déclaré la coupure** (rien en 300 s) ; les messages attendaient
  dans la file et sont arrivés d'un coup au retour, retardés mais pas
  perdus. Pendant la passe n°2, les coupures ont bien été déclarées : les
  deux comportements existent.

| Paramètre | Ancienne valeur | Nouvelle valeur | Dérivation | Statut |
| --- | --- | --- | --- | --- |
| `connection_setup_s` | 7 s (banc, < 1 m) | **12 s** | reconnexion au retour à portée, sur le terrain | **mesuré** (quelques coupures, 2 passes) ; les 26–80 s plus loin ne sont pas modélisés |
| `connection_setup_mah` (`EnergyConfig`) | 0,028 mAh | **0,048 mAh** | 12 s à +14,5 mA, voir `docs/energie/consommation.md` | durée mesurée, courant mesuré au banc |
| `connection_idle_timeout_s` | 30 s | 30 s | — | **estimé**, inchangé |
| `max_concurrent_links` | 6 | 6 | — | **estimé**, inchangé (il faut 3 téléphones ou plus pour le mesurer) |

**Non modélisé** : le lien fantôme. Le simulateur ferme toujours une
connexion dès que la paire sort de portée, et le message reste chez
l'émetteur, libre de passer par un autre voisin. Dans l'app, un lien
fantôme peut au contraire retenir des messages et occuper une place de
connexion.

## 5. Taille des messages sur le fil

Calculée depuis le code de l'app (pas mesurée à l'antenne) :

| Contenu | Taille sur le fil |
| --- | --- |
| « ok » | ~1 000 o |
| texte typique (52 o) | ~1 650 o |
| texte de 200 o | ~3 800 o |
| accusé de réception | ~210 o |

La cause est un double JSON où les octets sont écrits comme des listes de
nombres, plus le chiffrement (X25519 et XChaCha20-Poly1305, ~72 o). L'en-tête
propre à Nearby n'est pas compté. Un format binaire ou base64 diviserait ces
tailles par ~4, mais casserait la compatibilité entre deux versions de
l'app : décision en attente.

| Paramètre | Ancienne valeur | Nouvelle valeur | Dérivation | Statut |
| --- | --- | --- | --- | --- |
| `TrafficConfig.payload_size_range_bytes` | 20 à 512 o (le texte) | **1 000 à 3 800 o** | de « ok » à un texte de 200 o, tirage uniforme (moyenne 2 400 o, un peu au-dessus du message typique de 1 650 o) | **calculé** |
| `RoutingAlgorithm.ack_size_bytes` | 8 o | **210 o** | un accusé de réception de l'app | **calculé** |
| `ack_size_bytes` de `tide_g2` et `geo_spray_focus` | 20 o | **222 o** | 210 + 12 o de position | **calculé** pour 210, position **estimée** |
| `ManagedFloodRouting(ack_size_bytes=...)` (`managed_flood`, `bitchat`) | 16 o | **210 o** | même format que les autres : on compare des algos pour l'app Nice, quelle que soit leur origine (Bluetooth Mesh, bitchat) | **calculé** |
| `BleConfig.summary_id_bytes` | 4 o | 4 o | — | **estimé**, inchangé |

**Non changé** : le PURGE_SYNC de `gossip_a` (Bloom de 128 o par
connexion), les annonces de `bitchat` et les beacons d'`eco_sf` (64 o)
suivent leur propre format et restent estimés. `managed_flood` envoie ses
accusés en diffusion, sans connexion, ce que l'app Nice ne fait pas : il
reste un « et si » sur un autre transport.

**Format allégé** (÷4) : `--set traffic.payload_size_range_bytes=250,950`.
Les accusés n'ont pas de raccourci, il faut changer `ack_size_bytes` dans le
code.

## 6. Population

- **iPhones** : aucun dans le réseau. L'app est Android uniquement, iOS est
  hors du projet ; un festivalier avec un iPhone est simplement un
  non-utilisateur (le taux d'adoption n'est pas encore modélisé, voir la
  TODO du README).
- **Honor (EMUI)** : l'app est gelée écran éteint, sauf réglage manuel. Non
  simulé.
- **Samsung avec les réglages d'usine** : pas encore testé.

## 7. Ce qui reste à mesurer

Par ordre d'importance pour le simulateur :

1. **Une vraie foule**, les corps répartis sur tout le trajet (sortie
   d'amphi, file de cantine, concert) : portée, exposant et débit. C'est la
   mesure qui manque le plus.
2. **3 téléphones ou plus** : connexions simultanées (`max_concurrent_links`)
   et débit avec 2 ou 3 voisins. Il faut emprunter des Android (Nearby
   n'existe que sur Android, un émulateur n'a pas de vrai Bluetooth).
3. **Reconnexion ×10** à 1, 10 et 30 m, pour une distribution du délai de
   connexion plutôt qu'une valeur fixe.
4. **Une passe libre n°3**, sens de la passe n°2 mais port de charge vers le
   marcheur : départage l'orientation et le terrain dans les ~11 dB d'écart.
5. **Usage en festival** : temps écran, messages par heure (relevés
   « Bien-être numérique », sondage).

## 8. Comparabilité avec les archives

Les runs archivés avant le 16 oct. 2026 utilisaient 37 ko/s,
`signal_margin_cutoff_db=6` et `weak_signal_max_probability=0.30`, 7 s de
connexion (0,028 mAh), des messages de 20 à 512 o et des accusés de 8 o
(20 o pour `tide_g2`/GSF, 16 o pour `managed_flood`/`bitchat`). Leurs
colonnes de livraison, de latence, d'overhead et d'énergie mesh ne sont pas
comparables aux nouvelles : les messages sont 5 à 7 fois plus lourds, les
accusés 26 fois plus, et les connexions mettent plus longtemps à s'ouvrir.
La config exacte de chaque run est dans son `.json`. La portée (30 m, 60 m)
n'a pas changé.
