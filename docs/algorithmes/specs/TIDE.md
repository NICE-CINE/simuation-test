# TIDE — Spécification

TIDE (*Tokens, Islands, Density, Energy*) : spray-and-focus à jetons pondérés par l'utilité, livraison directe dans les îlots, élection de relais selon la densité et l'énergie, réinjection par la source.

> **Statut** : implémenté dans `src/festival_ble_sim/routing/tide.py` (`--routing tide`), 8 tests dans `tests/test_routing_tide.py`. Base de TIDE-G et TIDE-G2 (`docs/algorithmes/specs/TIDE-G.md`, `docs/algorithmes/specs/TIDE-G2.md`). Le document d'origine (« NICE — Algorithmes de routage candidats et protocole de comparaison ») n'est pas dans le dépôt : cette spec est rédigée a posteriori à partir du code et décrit la réduction implémentée. Fiche courte : `docs/algorithmes/tide.md`.

---

## 1. Principe

1. **Utilité** : chaque nœud estime ses chances de croiser le destinataire, à partir de PRoPHET et de la fraîcheur de sa dernière rencontre directe, pondérées par son énergie.
2. **Jetons** : un message naît avec un budget de copies qui dépend de la densité locale. Les jetons sont partagés au prorata de l'utilité ; la dernière copie n'avance que vers un nœud d'utilité nettement meilleure.
3. **Îlots** : un voisin qui voit le destinataire en ce moment reçoit toujours une copie, qu'il livre au tick suivant.
4. **Élection** : en foule dense, seuls des relais élus portent les messages des autres ; les nœuds en batterie faible n'en portent jamais.
5. **Réinjection** : la source garde une copie fantôme et rajoute des jetons à 3, 6 et 20 minutes si le message n'est pas livré.
6. **Purge** : dès la livraison, les copies sont supprimées.

---

## 2. Spécification

### 2.1 État

| État | Portée | Contenu |
|---|---|---|
| `P[a][b]`, `horloge[a][b]` | global | prédictabilité PRoPHET et instant de sa dernière mise à jour |
| `dernière_rencontre[a][b]` | global | dernier tick où `a` et `b` étaient à portée |
| `voisins[a]` | global | voisins de `a` au tick courant (vue à 2 sauts) |
| `ρ[a]` | global | densité locale lissée |
| `relais[a]`, `prochaine_élection[a]`, `dernier_relais_vu[a]` | global | état de l'élection |
| `synchros[a]` | global | fenêtre d'une minute et pairs déjà servis |
| `livrés` | global | `msg_id` livrés |
| `tokens`, `l0`, `reinjections` | par copie | jetons, budget initial, réinjections faites |

### 2.2 Rencontres et densité (`on_tick`)

À chaque tick, pour chaque nœud `a` et chacun de ses voisins `b` :

```
si (a, b) n'était pas à portée au tick précédent :      // un contact long = une rencontre
    p = P_vieilli(a, b)
    P[a][b] ← p + (1 − p) · P_INIT
dernière_rencontre[a][b] ← t
ρ[a] ← (1 − α) · ρ[a] + α · |voisins(a)|               // ρ initial = |voisins(a)|
```

Vieillissement, calculé à la lecture : `P_vieilli(a, b) = P[a][b] · γ^((t − horloge[a][b]) / 30 s)`.

Transitivité (désactivée par défaut, en O(N²) à 4 000 nœuds) : `P[a][c] ← p + (1 − p) · P(a,b) · P(b,c) · β`.

### 2.3 Utilité

```
F(a, d) = exp(−(t − dernière_rencontre[a][d]) / τ)       (0 si jamais rencontré)
U(a, d) = min(1, e(a) · [w · P_vieilli(a, d) + (1 − w) · F(a, d)])

e(a) = 1                          si batterie ≥ 50 %
     = 0,2                        si batterie ≤ 20 %
     = 0,2 + 0,8 · (b − 0,2)/0,3  entre les deux
```

Les bornes (batterie illimitée) ont `e = 1`.

### 2.4 Élection des relais

Toutes les `election_period_s` pour chaque nœud :

```
si feuille (téléphone sous leaf_battery_pct)                     → membre
si relais sortant qui porte encore des messages d'autres nœuds   → reste relais
sinon :
    p = 1                                    si ρ ≤ ρ_cible
      = min(1, ρ_cible / ρ · e / ē)          sinon     (ē = énergie moyenne des voisins)
    relais ← tirage(p)
```

Un nœud **agit comme relais** si c'est une borne, si l'élection est désactivée, s'il est élu, ou s'il n'a vu aucun relais ni aucune borne depuis `member_fallback_s` (repli). Une feuille n'agit jamais comme relais.

### 2.5 Budget initial et réinjection

À la première décision sur une copie sans jetons, en pratique chez la source :

```
L0 = clamp(round(l_max · sqrt(ρ_ref / ρ)), l_min, l_max)
```

Réinjection par la source, à chaque décision, selon l'âge du message :

| Âge | Jetons ajoutés |
|---|---|
| 180 s | `max(1, round(L0 / 2))` |
| 360 s | `max(1, L0)` |
| 1 200 s | `max(1, round(L0 / 2))` |

Le total reste plafonné à `l_max`.

### 2.6 Décision

Pour chaque message `m` (destinataire `d`) du porteur `A`, à chaque contact avec `B` :

```
si m est livré                                 → retirer m de A ; IGNORE
si B détient m ou l'a déjà reçu                → IGNORE
initialiser les jetons (§2.5) ; réinjection si A est la source
si A a déjà servi max_syncs pairs distincts dans la minute et B n'en fait pas partie → IGNORE
si d ∈ voisins(B)                              → FORWARD (îlot)
si B n'agit pas comme relais (§2.4)            → IGNORE
si tokens > 1                                  → FORWARD (spray)
si tokens = 1 et U(B, d) > U(A, d) + δ         → FORWARD (focus)
sinon                                          → IGNORE
```

### 2.7 Effet d'un transfert (`on_forward`)

| Raison | Copie de A | Copie de B |
|---|---|---|
| îlot | inchangée | 0 jeton (ne sera plus relayée, seulement livrée) |
| spray | `n − k_B` jetons | `k_B = clamp(round(n · U_B / (U_A + U_B)), 1, n − 1)` ; part 0,5 si les deux utilités sont nulles |
| focus | supprimée, sauf chez la source qui garde une copie fantôme à 0 jeton pour la réinjection | 1 jeton |

`B` est ajouté aux pairs servis de `A` pour la minute en cours.

### 2.8 Purge et buffer

- **Purge** : à la livraison, `msg_id` entre dans `livrés`. Une copie livrée est retirée quand son porteur la réexamine dans `decide`, ou évincée en priorité.
- **Éviction** (`choose_eviction`), jamais un message dont le nœud est la source. Ordre : d'abord les messages livrés, puis les expirés, puis ceux de plus de `late_after_s`, puis les copies à ≤ 1 jeton, puis l'utilité la plus faible, puis le plus de sauts.

---

## 3. Paramètres

| Paramètre | Défaut | Rôle |
|---|---|---|
| `w` | 0,5 | poids de PRoPHET face à la fraîcheur |
| `tau_s` (`τ`) | 1 200 s | constante de temps de la fraîcheur |
| `p_encounter_init`, `beta`, `gamma` | 0,75 ; 0,25 ; 0,98 par 30 s | PRoPHET |
| `enable_transitivity` | `False` | transitivité PRoPHET |
| `rho_target` (`ρ_cible`) | 15 | densité au-delà de laquelle l'élection limite les relais |
| `rho_ref`, `l_max`, `l_min` | 10 ; 16 ; 2 | budget initial (`l_max` relevé de 12 à 16 le 2 octobre, §6) |
| `delta` (`δ`) | 0,05 | hystérésis du focus |
| `election_period_s` | 300 s | période d'élection |
| `member_fallback_s` | 30 s | repli : un membre relaie s'il ne voit aucun relais depuis ce délai |
| `leaf_battery_pct` | 0,15 | seuil des feuilles |
| `max_syncs_per_minute` | 5 | pairs servis par minute et par porteur (`None` = illimité) |
| `late_after_s` | 600 s | âge à partir duquel un message est « en retard » pour l'éviction |
| `reinjection_schedule_s` | (180, 360, 1 200) | instants de réinjection |
| `density_ewma_alpha` (`α`) | 0,1 | lissage de la densité, par tick |
| `seed` | 0 | graine du tirage d'élection |

**Interrupteurs d'ablation** (tous `True` par défaut) : `islands`, `weighted_tokens` (sinon partage 50/50), `election` (sinon tout le monde relaie), `reinjection`, `energy_factor` (sinon `e = 1`).

`main.py` passe `seed=args.seed`. `scripts/compare_algorithms.py` instancie `TideRouting()` sans argument (graine 0).

---

## 4. Implémentation dans le simulateur

- Une seule instance partagée lit le voisinage de chaque nœud dans `on_tick` : la vue à 2 sauts, la densité, l'énergie des voisins et la table de rencontres n'ont pas besoin de format d'annonce ni d'échange GATT.
- Hooks : `on_simulation_start`, `on_tick`, `decide`, `on_forward`, `on_delivered`, `choose_eviction`.
- **Points d'extension pour TIDE-G** : `_before_route`, `_spray_ok`, `_focus_ok` et `_token_share` sont surchargés par `TideGRouting` (`tide_g.py`). Toute modification de TIDE se répercute sur `tide_g` et `tide_g2`.

---

## 5. Ce qui est simplifié

Non modélisés : chiffrement, identifiants éphémères, digests de buffer, intervalle d'annonce et cycle de scan (le moteur ne facture pas l'énergie de découverte), dérive d'horloge (âge = `t − création`), quota de buffer par émetteur, réputation, ordre de transmission « retardataires d'abord » (l'ordre d'envoi appartient au moteur). Les ACK purgent instantanément à l'échelle du réseau, comme dans `dasfv`.

---

## 6. Points d'attention

- **Réglage du 2 octobre** (spec et plan dans `docs/superpowers/specs|plans/2026-10-02-tide-optimisation*`, archives `archives/2026-10-0[23]_*tune*`) : sur 1 000 festivaliers, 900 s, `random_waypoint`, graines 1 à 4, `l_max` 16 au lieu de 12 donne +4,1 points de livraison (positif sur chaque graine), overhead ×1,11 et énergie ×1,19. Deux corrections de logique ont été rejetées par ablation et retirées du code : pas de spray vers un contact trop dense (−3 à −23 points) et une seule copie d'îlot par message (+0,6 point, dans le bruit). **La validation à grande échelle (4 000 festivaliers, graine 42) n'a jamais été archivée** : le gain n'est établi que sur le scénario réduit.
- **Résultats antérieurs** : les campagnes de `docs/algorithmes/specs/TIDE-G2.md` et `docs/algorithmes/specs/GSF.md` ont été mesurées avec `l_max = 12`. Leurs lignes TIDE, TIDE-G et TIDE-G2 ne reflètent plus les défauts actuels.
- **Beaucoup de paramètres** : calibration délicate.
- **Vues exactes** de l'instance partagée (2 sauts, densité, purge) : optimistes face à de vraies annonces BLE.
- **Gains invisibles** : le moteur ne facture ni la découverte ni les connexions, donc les économies attendues des digests et du cycle de scan ne sont pas mesurables ici.
- **Repli lent** : un membre sans relais à portée attend 30 s avant de relayer lui-même.
- **Éviction** : si le buffer ne contient que des messages propres, `choose_eviction` renvoie `None` et le moteur évince en FIFO, donc un message propre.
- **Purge paresseuse** : une copie livrée reste en buffer jusqu'à ce que son porteur la réexamine ou l'évince ; elle ne consomme rien en attendant, car `decide` l'écarte avant tout envoi.
- **Résultats** : à 400 festivaliers en mobilité `poi`, TIDE livre 49 à 55 % avec `l_max = 12` (`docs/algorithmes/specs/TIDE-G2.md` §5).
