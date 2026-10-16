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
