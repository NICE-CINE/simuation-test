# Modèle de consommation et charge de départ

> **Statut** : valeurs recalées le 12 oct. 2026 sur le banc radio Nice Mesh
> (IMT Mines Alès), écran mesuré le 13 oct. Chaque paramètre indique s'il est **mesuré** ou **estimé**.
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
| `phone_current_ma` | 98 mA (écran estimé à ~300 mA) | **82 mA** | repos écran éteint 38 mA (moyenne de 27 et 49) + écran allumé 20 % du temps à +218 mA (voir ci-dessous) | repos et surcoût écran **mesurés**, part de 20 % **estimée** |
| `tx_cost_mah_per_byte` | 2,8e-7 | **2,4e-7** | milieu de 0,25–0,6 µJ/bit à 3,84 V | mesuré |
| `rx_cost_mah_per_byte` | 2,8e-7 | **6,3e-8** | milieu de 0,07–0,16 µJ/bit à 4,04 V | mesuré |
| `tx_cost_mah_per_event` | 1,4e-5 | **2,9e-5** | ~5 ms d'antenne à +21 mA | courant mesuré, durée supposée |
| `rx_cost_mah_per_event` | 1,4e-5 | **1,7e-5** | ~5 ms d'antenne à +12 mA | courant mesuré, durée supposée |
| `initial_charge_bins` | — | **100 % pour tous** (défaut) ; tranches avec `--random-charge` | voir §4 | choisi |
| `connection_setup_mah` | — (connexion gratuite) | **0,028** | 7 s de découverte (`BleConfig.connection_setup_s`, mesuré) à +14,5 mA (« BLE annonces + scan » : +18 et +11 mA), sur chacun des deux téléphones | courant et durée mesurés, assimilation à une phase d'annonce + scan **supposée** |
| `extra_connection_current_ma` | — | **3 mA** | chaque connexion tenue au-delà de la première, par téléphone (`background_current_ma` a été mesuré avec une seule) | **estimé** |

L'ancienne réception coûtait autant que l'émission, soit 3 à 7 fois trop cher.
L'ancien courant de fond (2 mA) était environ 15 fois trop bas.

### Écran allumé (mesuré le 13 oct.)

Téléphone débranché, luminosité manuelle à 50 %, app au premier plan, lien
Nearby connecté. Moyenne de 120 échantillons (1/s) par écran, après 20 s de
stabilisation. Surcoût par rapport à l'écran éteint de la même série :

| Écran | Honor 8X | Galaxy A56 |
| --- | --- | --- |
| Onglet Amis (liste statique) | 336 mA (+244) | 196 mA (+128) |
| Onglet Carte (rendu, GPS toutes les 5 s, orientation) | 388 mA (+296) | 287 mA (+219) |
| Conversation | 367 mA (+275) | 216 mA (+148) |
| Écran éteint (référence de la série) | 92 mA | 68 mA |

Surcoût moyen : +272 mA (Honor), +165 mA (Samsung), soit **+218 mA**
pour les deux. L'ancienne estimation (~300 mA) correspondait au courant
total écran allumé, pas au surcoût, et surestimait le téléphone de 16 mA.

Limites de cette mesure :

- **Référence écran éteint instable** : 92 mA (Honor) et 68 mA (Samsung)
  dans cette série, contre 56 et 83 mA pour « Nearby actif » sur le banc du
  12 oct. Le surcoût est pris par rapport à la référence de la même série ;
  calculé sur celle du 12 oct., il passerait à environ +308 mA sur le Honor.
- **Moyenne simple des trois écrans** : cela suppose un temps écran réparti
  également entre Amis, Carte et Conversation, et passé entièrement dans
  l'app. Avec la Carte seule (+296 / +219 mA), on aurait environ 89 mA.
- **Luminosité fixée à 50 %** : en plein jour, la luminosité automatique est
  proche du maximum, donc le surcoût réel est probablement plus élevé.
- **GPS** : l'onglet Carte fait un fix toutes les 5 s, donc une petite part
  de GPS (de l'ordre de 1 mA sur les 82) est déjà dans `phone_current_ma`.
  `tide_g`, `tide_g2` et `geo_spray_focus` facturent en plus leurs propres
  fix (`gps_current_ma`) : ce double compte est négligeable.

### Ce qui est facturé, et où

- **Chaque tick, chaque téléphone actif** paie
  `background_current_ma + phone_current_ma`, soit 113 mA
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

### Deux colonnes d'énergie

Le rapport donne deux mesures, sur les téléphones seulement (bornes exclues) :

- **Énergie totale** (`total_energy_consumed_mah`, `avg_energy_consumed_mah`) :
  tout ce que la batterie a perdu, téléphone compris. C'est elle qui décide
  quand un téléphone meurt.
- **Énergie mesh** (`total_mesh_energy_consumed_mah`,
  `avg_mesh_energy_consumed_mah`, ligne « dont mesh » du rapport) : la même
  chose **sans** `phone_current_ma`, c'est-à-dire rester joignable, plus
  l'émission, la réception et les coûts propres aux algorithmes. **C'est la
  colonne à utiliser pour comparer les algorithmes** : les 82 mA du
  téléphone sont identiques pour tous et masqueraient les écarts.

`BaseNode.consume_energy(mah, mesh=False)` est le seul appel qui ne compte
pas dans la part mesh ; tout nouveau coût facturé par un algorithme y
entre par défaut. `compare_algorithms.py` écrit les deux totaux dans son CSV.

Pour ne simuler que le mesh, sans le téléphone lui-même :
`EnergyConfig(phone_current_ma=0.0)`.

### Autonomie qui en découle

À 113 mA, un téléphone perd environ 2,5 % de sa capacité par heure :

| Charge de départ | mAh | Autonomie |
| --- | --- | --- |
| 100 % | 4 500 | ~40 h |
| 50 % | 2 250 | ~20 h |
| 30 % | 1 350 | ~12 h |
| 5 % | 225 | ~2 h |

Sans le mesh (82 mA seulement), un téléphone plein tient environ 55 h.
Le mesh coûte donc environ 27 % de l'autonomie.

## 3. Capacité et charge : deux grandeurs distinctes

Chaque nœud distingue :

- `battery_capacity_mah` : la capacité, qui vaut 100 % ;
- `initial_charge_mah` : la charge à l'arrivée, égale à capacité × fraction tirée ;
- `battery_mah` : la charge restante.

Deux usages, deux références :

- **Les pourcentages de batterie** des algorithmes (`tide`, `dasfv`,
  `fresh_spray`, `eco_sf`) passent tous par `BaseNode.battery_fraction`,
  calculé par rapport à la **capacité**. Un téléphone arrivé à 20 % est donc vu à 20 % dès le début.
  Le calcul par rapport à la charge de départ le verrait à 100 %.
- **L'énergie consommée** du rapport (`energy_consumed_mah`) est mesurée
  depuis la **charge de départ**. Un téléphone qui meurt n'a dépensé que ce
  qu'il avait en arrivant.

## 4. Charge de départ aléatoire

Par défaut, tout le monde arrive à 100 % : la tranche unique
`(1.0, 1.0, 1.0)` donne exactement 1,0 à chaque tirage, et les runs sont
identiques à ceux d'avant cette option. Avec
`--random-charge` (dans `main.py` et `compare_algorithms.py`, via
`presets.add_random_charge_argument` et `presets.energy_config`), chaque
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
| `dasfv` | mule ≥ 40 % ; évacuation sous 30 % (delta forcé à 0) ; batterie faible 15 % | ~14 % ; ~8 % ; ~3 % |
| `tide` | facteur d'énergie réduit sous 50 % ; minimal sous 20 % ; feuille sous 15 % | ~20 % ; ~5 % ; ~3 % |
| `fresh_spray` | refus des pairs sous 15 % | ~3 % |
| `eco_sf` | Trickle allongé sous 50 % (30 → 60 s) ; sous 20 % : 120 s et plus choisi comme relais ; silencieux sous 10 % | ~20 % ; ~5 % ; ~2 % |

**Téléphones à plat** (`dead_node_count`). À 113 mA, un téléphone meurt
pendant le run s'il arrive sous 2,5 % × durée en heures. Pour un run de
3 h, plus 30 min de cooldown, ce seuil est d'environ 9 % : environ 1,2 %
des téléphones meurent en cours de route. Sur un run d'1 h, aucun ne meurt.

## 5. Ce qui n'est pas modélisé

- **Écran** : le surcoût de l'écran allumé est mesuré (à 50 % de luminosité,
  dans l'app seulement, voir §2), mais la part de 20 % du temps écran allumé
  est une estimation. À recalibrer si l'équipe mesure un usage réel en
  festival.
- **Réseau cellulaire saturé** : un téléphone qui cherche du réseau dans une
  foule consomme beaucoup plus. Ce n'est compté nulle part.
- **Débit** : `BleConfig.transfer_rate_bytes_per_s` vaut 31 ko/s, mesurés
  sur le terrain avec 5 personnes devant un téléphone (voir
  `docs/radio/mesures.md`) ; les autres téléphones agissent par la charge du
  canal (collisions, retransmissions), pas par ce chiffre.
- **Connexion** : Nearby met environ 7 s entre la découverte et la
  connexion (`BleConfig.connection_setup_s`). Ces 7 s sont facturées au
  courant « annonces + scan » (`connection_setup_mah`), et chaque connexion
  au-delà de la première 3 mA (`extra_connection_current_ma`) : ni l'un ni
  l'autre n'a été mesuré à part, c'est le prochain banc à faire.
- **EMUI (Huawei/Honor)** : avec les réglages par défaut, l'app est gelée
  écran éteint, et le téléphone est en pratique hors réseau. Ce n'est pas
  simulé.

## 6. Comparabilité avec les archives

Les runs archivés avant ce recalage utilisaient 3 000 mAh, 2 mA de fond et
une réception aussi chère que l'émission. Leurs colonnes d'énergie ne sont
pas comparables aux nouvelles. Ces archives n'ont pas non plus la colonne
`total_mesh_energy_consumed_mah`. La config exacte de chaque run se trouve
dans son `.json`. Les colonnes de livraison, de latence et d'overhead ne
changent pas : aucun seuil de batterie ne se déclenche à 100 % de charge.

Les runs archivés entre ce recalage et la mesure de l'écran (13 oct.)
utilisaient `phone_current_ma = 98` au lieu de 82. Leur énergie totale est
environ 14 % plus haute et leur `dead_node_count` un peu plus élevé avec
`--random-charge`. Leur énergie mesh reste comparable, et les autres
colonnes aussi à 100 % de charge. La valeur utilisée est dans le `.json`.
