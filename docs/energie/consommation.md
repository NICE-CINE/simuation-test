# Modèle de consommation et charge de départ

> **Statut** : valeurs recalées le 12 oct. 2026 sur le banc radio Nice Mesh
> (IMT Mines Alès). Chaque paramètre indique s'il est **mesuré** ou **estimé**.
> Code : `EnergyConfig` (`src/festival_ble_sim/config.py`), facturation dans
> `simulation.py` (courant de fond) et `network.py` (émission/réception).

## 1. D'où viennent les chiffres

Le banc a mesuré la couche de transport de l'app (Google Nearby Connections,
stratégie `P2P_CLUSTER`, qui passe en pratique par du **Bluetooth classique**)
sur deux téléphones réels, écran éteint et sur batterie :

| | Honor 8X | Galaxy A56 |
| --- | --- | --- |
| Batterie / tension mesurée | 3 750 mAh · 3,84 V | 5 000 mAh · 4,04 V |
| Repos (mesh coupé, BT allumé) | 27 mA | 49 mA |
| BLE annonces + scan | 45 mA (+18) | 60 mA (+11) |
| Nearby actif, connecté, sans trafic | 56 mA (+29) | 83 mA (+34) |
| Envoi continu (surcoût sur « Nearby actif ») | +21 mA | invalide |
| Réception continue (surcoût sur « Nearby actif ») | +13 mA | +11 mA |

Rapporté au débit mesuré (0,14 à 0,63 Mbit/s selon le sens) :

- **émission** : 0,25 à 0,6 µJ/bit, soit environ 2 à 5 J par Mo ;
- **réception** : 0,07 à 0,16 µJ/bit, soit environ 0,6 à 1,3 J par Mo.

Le banc conclut que **ce qui coûte, c'est d'être joignable** : garder Nearby
actif coûte plus (+29 à +34 mA) que d'envoyer ou de recevoir (+11 à +21 mA).

Limites des mesures : deux téléphones à moins d'un mètre, une série par
phase. Ce sont des ordres de grandeur.

## 2. Paramètres du simulateur

Conversion : 1 mAh = 3,6 C ; énergie = charge × tension (3,84 à 4,04 V).
Par exemple 2,4e-7 mAh/octet × 3,6 × 3,84 V ≈ 3,3 µJ/octet ≈ 0,42 µJ/bit.

| Paramètre | Ancienne valeur | Nouvelle valeur | Dérivation | Statut |
| --- | --- | --- | --- | --- |
| `battery_capacity_mah` | 3 000 (`initial_battery_mah`) | **4 500** | téléphone récent typique, entre les deux du banc | choisi |
| `background_current_ma` | 2 mA | **31 mA** | « Nearby actif, connecté, sans trafic » : +29 à +34 mA | mesuré |
| `phone_current_ma` | — | **98 mA** | repos écran éteint 38 mA (moyenne de 27 et 49) + écran allumé 20 % du temps à ~300 mA | repos **mesuré**, écran **estimé** |
| `tx_cost_mah_per_byte` | 2,8e-7 | **2,4e-7** | milieu de 0,25–0,6 µJ/bit à 3,84 V | mesuré |
| `rx_cost_mah_per_byte` | 2,8e-7 | **6,3e-8** | milieu de 0,07–0,16 µJ/bit à 4,04 V | mesuré |
| `tx_cost_mah_per_event` | 1,4e-5 | **2,9e-5** | ~5 ms d'antenne à +21 mA | courant mesuré, durée supposée |
| `rx_cost_mah_per_event` | 1,4e-5 | **1,7e-5** | ~5 ms d'antenne à +12 mA | courant mesuré, durée supposée |
| `initial_charge_bins` | — | **100 % pour tous** (défaut) ; tranches avec `--random-charge` | voir §4 | choisi |

L'ancienne réception coûtait autant que l'émission, soit 3 à 7 fois trop cher.
L'ancien courant de fond (2 mA) était environ 15 fois trop bas.

### Ce qui est facturé, et où

- **Chaque tick, chaque téléphone actif** paie
  `background_current_ma + phone_current_ma`, soit 129 mA
  (`simulation._mobile_process`). Ce poste représente plus de 95 % de la
  consommation d'un run : les écarts d'énergie entre algorithmes viennent
  des seuls coûts d'émission et de réception.
- **Chaque transmission** (`network.process_node_contacts`) : l'émetteur paie
  `cost_of_tx`, le récepteur `cost_of_rx`. Une transmission perdue ne coûte
  que l'émission.
- **Coûts propres à un algorithme** : ACK de `managed_flood` (même modèle
  tx/rx), fix GPS de `tide_g`/`tide_g2`/`geo_spray_focus`
  (`gps_current_ma`, hypothèse non mesurée).
- Les **bornes** sont sur secteur (`battery_mah = inf`) et exclues du rapport.

Pour ne mesurer que le surcoût du mesh, sans le téléphone lui-même :
`EnergyConfig(phone_current_ma=0.0)`.

### Autonomie qui en découle

À 129 mA, un téléphone perd environ 2,9 % de sa capacité par heure :

| Charge de départ | mAh | Autonomie |
| --- | --- | --- |
| 100 % | 4 500 | ~35 h |
| 50 % | 2 250 | ~17 h |
| 30 % | 1 350 | ~10 h |
| 5 % | 225 | ~1 h 45 |

Sans le mesh (98 mA seulement), un téléphone plein tient environ 46 h.
Le mesh coûte donc environ un quart de l'autonomie.

## 3. Capacité et charge : deux grandeurs distinctes

Chaque nœud distingue :

- `battery_capacity_mah` : la capacité, qui vaut 100 % ;
- `initial_charge_mah` : la charge à l'arrivée, égale à capacité × fraction tirée ;
- `battery_mah` : la charge restante.

Deux usages, deux références :

- **Les pourcentages de batterie** des algorithmes (`_battery_pct` dans
  `tide`, `dasfv`, `fresh_spray`, `eco_sf`) sont calculés par rapport à la
  **capacité**. Un téléphone arrivé à 20 % est donc vu à 20 % dès le début.
  Le calcul par rapport à la charge de départ le verrait à 100 %.
- **L'énergie consommée** du rapport (`energy_consumed_mah`) est mesurée
  depuis la **charge de départ**. Un téléphone qui meurt n'a dépensé que ce
  qu'il avait en arrivant.

## 4. Charge de départ aléatoire

Par défaut, tout le monde arrive à 100 %, et le simulateur ne fait aucun
tirage : les runs sont identiques à ceux d'avant cette option. Avec
`--random-charge` (dans `main.py` et `compare_algorithms.py`), chaque
téléphone tire sa charge selon `presets.FESTIVAL_CHARGE_BINS` :

| Part des festivaliers | Charge de départ |
| --- | --- |
| 50 % | 80 – 100 % |
| 30 % | 50 – 80 % |
| 12 % | 30 – 50 % |
| 8 % | 5 – 30 % |

Fonctionnement :

- Chaque téléphone choisit une tranche selon ces parts, puis une valeur
  uniforme dans la tranche (`simulation.draw_charge_fraction`).
- Le tirage utilise son propre générateur, `random.Random(f"{seed}-charge")`.
  Une même graine donne donc les mêmes charges, et activer l'option ne
  décale aucun autre tirage (mobilité, trafic, radio).
- La charge moyenne est d'environ 71 %, soit environ 3 180 mAh.
- Tranches personnalisées en code :
  `EnergyConfig(initial_charge_bins=((part, bas, haut), ...))`. Les parts sont
  des poids relatifs, et `0 < bas <= haut <= 1`.
- La config résolue, tranches comprises, est archivée dans le `.json` de
  chaque run.

### Effets attendus

**Seuils de batterie des algorithmes.** Avec 100 % pour tous, ils ne se
déclenchaient jamais sur des runs de 1 à 3 h. Avec `--random-charge`,
voici la part des téléphones déjà sous le seuil dès l'arrivée :

| Algorithme | Seuil | Part sous le seuil |
| --- | --- | --- |
| `dasfv` | mule ≥ 40 % ; batterie faible 15 % | ~14 % ; ~3 % |
| `tide` | facteur d'énergie réduit sous 50 %, minimal sous 20 % ; feuille sous 15 % | ~20 % ; ~3 % |
| `fresh_spray` | refus des pairs sous 15 % | ~3 % |
| `eco_sf` | Trickle allongé sous 50 % (30 → 60 s) ; sous 20 % : 120 s et plus choisi comme relais ; silencieux sous 10 % | ~20 % ; ~5 % ; ~2 % |

**Téléphones à plat** (`dead_node_count`). À 129 mA, un téléphone meurt
pendant le run s'il arrive sous 2,9 % × durée en heures. Pour un run de
3 h, plus 30 min de cooldown, ce seuil est d'environ 10 % : environ 1,6 %
des téléphones meurent en cours de route. Sur un run d'1 h, aucun ne meurt.

## 5. Ce qui n'est pas modélisé

- **Écran** : la part de 20 % d'écran allumé à ~300 mA est une estimation,
  pas une mesure. À recalibrer si l'équipe mesure un usage réel en festival.
- **Réseau cellulaire saturé** : un téléphone qui cherche du réseau dans une
  foule consomme beaucoup plus. Ce n'est compté nulle part.
- **Débit** : `BleConfig.transfer_rate_bytes_per_s` reste à 10 ko/s
  (BLE GATT en foule dense). Le banc mesure environ 37 ko/s en Bluetooth
  classique, entre deux téléphones seuls. Modifier ce débit changerait les
  taux de livraison, pas seulement l'énergie, donc il n'a pas été touché.
- **Connexion** : Nearby met environ 7 s entre la découverte et la
  connexion. Dans le simulateur, un contact est utilisable dès le premier
  tick.
- **EMUI (Huawei/Honor)** : avec les réglages par défaut, l'app est gelée
  écran éteint, et le téléphone est en pratique hors réseau. Ce n'est pas
  simulé.

## 6. Comparabilité avec les archives

Les runs archivés avant ce recalage utilisaient 3 000 mAh, 2 mA de fond et
une réception aussi chère que l'émission. Leurs colonnes d'énergie ne sont
pas comparables aux nouvelles. La config exacte de chaque run se trouve
dans son `.json`. Les colonnes de livraison, de latence et d'overhead ne
changent pas : aucun seuil de batterie ne se déclenche à 100 % de charge.
