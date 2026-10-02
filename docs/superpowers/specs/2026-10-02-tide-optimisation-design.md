# Optimisation de TIDE et TIDE-G — design

## Objectif

Augmenter le taux de livraison de `tide` et `tide_g` sans dégrader
sensiblement l'overhead ni l'énergie. Les autres algorithmes ne sont pas
touchés.

## Critères de succès

- **Métrique principale :** `delivery_ratio`.
- **Garde-fous :** `overhead` et `total_energy_consumed_mah` au plus +20 % par
  rapport à la référence du même algorithme (TIDE ou TIDE-G avec les valeurs
  par défaut actuelles).
- **Seuil de bruit :** un changement n'est retenu que si son gain moyen
  dépasse 1 point de livraison sur les seeds de réglage, avec le même signe
  sur chaque seed.
- **Validation finale :** scénario complet (4 000 festivaliers, 3 600 s,
  seed 42, 10 balises, `reply_probability=0.5`). Le nouveau défaut doit battre
  l'ancien sur la livraison, en respectant les garde-fous.

## Scénario de réglage

Le scénario complet prend plus de 30 min par run, trop long pour itérer. Le
réglage se fait donc sur un scénario réduit : 1 000 festivaliers, 900 s,
10 balises, `random_waypoint`, `reply_probability=0.5`, seeds 1 et 2. On ne
règle jamais sur le seed 42, réservé à la validation, pour éviter le
surapprentissage.

Les réponses sont activées dans tout le benchmark : sans elles, aucun message
ne porte de `dst_position`, et TIDE-G se réduit à TIDE plus le coût du GPS
(mesure : énergie ×2,8, livraison −1 point).

## Phase A — réglage des paramètres

1. **Balayage un-facteur-à-la-fois** autour des valeurs par défaut :
   - TIDE : `l_max`, `l_min`, `rho_target`, `rho_ref`, `w`, `tau_s`, `delta`,
     `max_syncs_per_minute`, transitivité, calendrier de réinjection,
     `member_fallback_s`, plus les interrupteurs d'ablation existants ;
   - TIDE-G : `gps_for_relays`, `gps_period_s`, `zone_tokens`,
     `geo_lambda_m`, `min_progress_m`, `hint_max_age_s`, plus les
     interrupteurs.
2. **Combinaison** des variantes gagnantes (au-dessus du seuil de bruit et
   dans les garde-fous), vérifiée sur les seeds 1 à 3. Les interactions entre
   paramètres sont vérifiées là, pas présupposées.
3. **Nouveaux défauts** dans `TideRouting.__init__` et
   `TideGRouting.__init__`. Les tests qui supposent les anciens défauts sont
   mis à jour.

L'outil de balayage reste un script jetable (hors dépôt) : les CSV de résultats
qui justifient chaque choix sont archivés dans `archives/` avec leur `.json`,
comme les autres runs.

## Phase B — corrections de logique

Les candidats sont testés un par un, en ablation, sur la base de la phase A.
Chacun obtient un interrupteur de constructeur, comme les ablations
existantes. Un candidat qui ne passe pas le seuil de bruit est retiré du code,
pas laissé désactivé.

- **B1 — Contention.** TIDE a ~20 fois plus de pertes de paquets que PRoPHET
  sur le même scénario. Ne pas pulvériser (jetons > 1) vers un contact dont la
  densité de voisinage (`_density`, déjà calculée) dépasse un seuil : ces
  envois sont les plus exposés aux collisions de terminaux cachés.
- **B2 — Bornage des îles.** Aujourd'hui, *chaque* voisin qui voit la
  destination reçoit une copie (raison `island`). Limiter à une seule copie en
  île par message et par tick.
- **B3 — GPS des relais (TIDE-G).** Si la phase A montre que
  `gps_for_relays=False` ne coûte rien en livraison, c'est déjà réglé par un
  défaut, sans changer de logique. Sinon : relevé GPS pour un relais
  seulement quand un voisin porte un message avec indice.

Les candidats B sont des hypothèses. La liste peut être révisée à partir des
données de la phase A, avec mise à jour de ce spec.

## Hors périmètre

Les autres algorithmes, le moteur (`network.py`) et les paramètres de
`SimulationConfig`. Les docs (`README.md`, `docs/algorithmes/tide*.md`,
`docs/TIDE-G.md`) sont mises à jour uniquement pour refléter les nouveaux
défauts et les règles ajoutées.

## Tests

- `pytest` passe à chaque étape.
- Chaque règle de la phase B a un test unitaire ciblé dans le style de
  `tests/test_tide*.py`.
- Le résultat de la validation finale est archivé.
