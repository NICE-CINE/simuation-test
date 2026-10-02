# Optimisation de TIDE / TIDE-G — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relever le taux de livraison de `tide` / `tide_g` par de nouveaux défauts (phase A) puis par des règles ajoutées seulement si elles passent l'ablation (phase B).

**Architecture:** Un script de réglage jetable (hors dépôt) lance des variantes `kwargs` de `TideRouting` / `TideGRouting` sur un scénario réduit, archive le CSV dans `archives/` et imprime un verdict par variante selon les critères du spec. Le code ne change que pour les nouveaux défauts et les règles B retenues ; chaque règle B est un paramètre de constructeur (`None`/`False` = désactivée) testé unitairement.

**Tech Stack:** Python 3.9, SimPy, pytest, `concurrent.futures`.

**Spec:** `docs/superpowers/specs/2026-10-02-tide-optimisation-design.md`

## Global Constraints

- Python 3.9 : pas de `X | Y`, pas de `match`, `typing.Optional/List/Dict/Set/Tuple`.
- Pas de commentaires sauf WHY non évident ; pas de docstrings.
- Métrique principale `delivery_ratio` ; garde-fous `overhead` et `total_energy_consumed_mah` ≤ +20 % vs la **référence** (anciens défauts du même algo).
- Seuil de bruit : gain moyen > 1 point de livraison **et** même signe (positif) sur chaque seed ; seeds 1 à 4.
- Scénario de réglage : 1 000 festivaliers, 900 s, 10 balises, `random_waypoint`, `reply_probability=0.5`. Le seed 42 n'est **jamais** utilisé pour régler.
- Validation : 4 000 festivaliers, 3 600 s, seed 42, 10 balises, `reply_probability=0.5`.
- Hors périmètre : autres algos, `network.py`, `SimulationConfig`.
- Un candidat B qui échoue est **retiré du code** (pas laissé désactivé).
- `pytest` vert à chaque commit. Fin de message de commit : `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Anciens défauts (référence)

À réutiliser tels quels dans chaque fichier de variantes, sous le label `ref` :

```json
{"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false}
```

Pour `tide_g`, la même chose plus `"gps_for_relays": true`.

## Review Focus

1. **Coût CPU de la transitivité** : `enable_transitivity` est en O(N²) et avait été désactivée pour 4 000 nœuds. La Task 2 la rejette si le temps de run moyen dépasse ×1,5 la référence, et la Task 6 rapporte le temps de chaque run complet.
2. **TIDE-G hérite des défauts de TIDE** : changer ceux de TIDE change TIDE-G. La Task 3 revérifie TIDE-G sur la nouvelle base, avec les anciens défauts complets comme référence.
3. **Tests épinglés aux anciens défauts** (`l_max=12` dans `test_initial_tokens_shrink_with_density`, `gps_for_relays` dans `test_relays_pay_for_their_gps_fixes`) : on passe la valeur explicitement dans le test, on n'affaiblit pas l'assertion.
4. **Runs sans réponses** (`reply_probability=0`, défaut de `main.py`) : les nouveaux défauts ne doivent pas y régresser. La Task 6 ajoute un run réduit sans réponses, anciens vs nouveaux défauts.
5. **Mémoire en validation** : 4 runs de 4 000 nœuds en parallèle. La Task 6 utilise 4 workers au plus ; si un worker est tué (OOM), relancer avec 2.

---

### Task 1: Script de réglage et archivage du premier balayage

**Files:**
- Create (hors dépôt) : `$SCRATCH/tune_tide.py`, où `$SCRATCH=/private/tmp/claude-501/-Users-nils-Desktop-IMT-simu/2b833fb7-e9ee-461c-9ccc-753770db5017/scratchpad`
- Copy : `$SCRATCH/sweep1.csv` → `archives/<stamp>_tune_tide_sweep1.csv` (résultats du balayage un-facteur-à-la-fois déjà fait, seeds 1 et 2)

**Interfaces:**
- Produces : `python $SCRATCH/tune_tide.py VARIANTS.json LABEL [--seeds 1 2 3 4] [--n 1000] [--duration 900] [--reply 0.5] [--workers 7] [--baseline LABEL] [--reference ref]`. `VARIANTS.json` = `{"tide": {label: kwargs}, "tide_g": {label: kwargs}}` (listes JSON converties en tuples). Écrit `archives/<stamp>_tune_<LABEL>.csv` + `.json` (via `archive_stem`/`write_params`), imprime une ligne par variante avec `PASS`/`fail`.

- [ ] **Step 1: Écrire le script**

```python
import argparse, csv, json, statistics, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict
sys.path.insert(0, "scripts")
from compare_algorithms import build_config
from festival_ble_sim.archive import archive_stem, write_params
from festival_ble_sim.routing.tide import TideRouting
from festival_ble_sim.routing.tide_g import TideGRouting
from festival_ble_sim.simulation import run_simulation

CLASSES = {"tide": TideRouting, "tide_g": TideGRouting}


def kwargs_of(raw):
    return {k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()}


def run(algo, label, raw, seed, n, duration, reply):
    t = time.time()
    r = run_simulation(build_config(10, seed, duration, n, reply_probability=reply),
                       routing_algorithm=CLASSES[algo](**kwargs_of(raw)))
    return dict(algo=algo, variant=label, seed=seed, delivery_ratio=r.delivery_ratio,
                avg_latency_s=r.avg_latency_s, overhead=r.overhead,
                energy=r.total_energy_consumed_mah, loss=r.packet_loss_count, wall_s=time.time() - t)


def summarise(rows, seeds, baseline, reference):
    g = defaultdict(dict)
    for r in rows:
        g[(r["algo"], r["variant"])][r["seed"]] = r
    for algo in sorted({a for a, _ in g}):
        base, ref = g.get((algo, baseline)), g.get((algo, reference))
        if base is None or ref is None:
            continue
        print(f"\n{algo}: delta vs '{baseline}', guardrails vs '{reference}'")
        lines = []
        for (a, v), d in g.items():
            if a != algo:
                continue
            deltas = [100 * (d[s]["delivery_ratio"] - base[s]["delivery_ratio"]) for s in seeds]
            ratio = lambda k: sum(d[s][k] for s in seeds) / sum(ref[s][k] for s in seeds)
            mean = statistics.mean(deltas)
            ok = mean > 1.0 and all(x > 0 for x in deltas) and ratio("overhead") <= 1.2 and ratio("energy") <= 1.2
            dr = statistics.mean(d[s]["delivery_ratio"] for s in seeds)
            lines.append((mean, f"{v:28s} dr={dr:.3f} d={mean:+5.1f} {['%+.1f' % x for x in deltas]} "
                                f"ovh x{ratio('overhead'):.2f} E x{ratio('energy'):.2f} t x{ratio('wall_s'):.2f} "
                                f"{'PASS' if ok else 'fail'}"))
        for _, line in sorted(lines, reverse=True):
            print(line)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("variants"); p.add_argument("label")
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--duration", type=float, default=900.0)
    p.add_argument("--reply", type=float, default=0.5)
    p.add_argument("--workers", type=int, default=7)
    p.add_argument("--baseline", default="ref")
    p.add_argument("--reference", default="ref")
    a = p.parse_args()
    variants = json.load(open(a.variants))
    jobs = [(algo, lbl, kw, s) for algo, vs in variants.items() for lbl, kw in vs.items() for s in a.seeds]
    stem = archive_stem("archives", f"tune_{a.label}")
    write_params(stem.with_suffix(".json"), {**vars(a), "variants": variants},
                 build_config(10, a.seeds[0], a.duration, a.n, reply_probability=a.reply))
    rows, t0 = [], time.time()
    with open(stem.with_suffix(".csv"), "w", newline="") as f, ProcessPoolExecutor(a.workers) as ex:
        w = None
        futs = [ex.submit(run, *j, a.n, a.duration, a.reply) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result(); rows.append(row)
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(row)); w.writeheader()
            w.writerow(row); f.flush()
            print(f"{i}/{len(jobs)} {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    print(f"archived: {stem}.csv")
    summarise(rows, a.seeds, a.baseline, a.reference)
```

- [ ] **Step 2: Test de fumée**

Run (depuis la racine du dépôt, venv actif) :
```bash
echo '{"tide": {"ref": {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false}, "same": {}}}' > $SCRATCH/smoke.json
python $SCRATCH/tune_tide.py $SCRATCH/smoke.json smoke --seeds 1 2 --n 60 --duration 120 --workers 2
```
Expected : `archived: archives/<stamp>_tune_smoke.csv`, puis deux lignes `ref` et `same` avec `d= +0.0` (même config, mêmes seeds → mêmes résultats). Supprimer ensuite `archives/*_tune_smoke.*`.

- [ ] **Step 3: Archiver le premier balayage**

```bash
cp $SCRATCH/sweep1.csv archives/2026-10-02_tune_sweep1.csv
cp $SCRATCH/sweep.py archives/2026-10-02_tune_sweep1.py.txt
git add archives/2026-10-02_tune_sweep1.*
git commit -m "chore(archives): first TIDE/TIDE-G one-factor sweep (seeds 1-2)"
```
(Le `.py.txt` tient lieu de `.json` : il contient les variantes exactes et le scénario.)

---

### Task 2: Nouveaux défauts de TIDE (combinaison)

**Files:**
- Modify : `src/festival_ble_sim/routing/tide.py` (signature de `TideRouting.__init__`)
- Modify : `tests/test_routing_tide.py:37-40` (`test_initial_tokens_shrink_with_density`)
- Modify : `README.md:274-288`, `docs/algorithmes/tide.md:10-24`

**Interfaces:**
- Consumes : `tune_tide.py` (Task 1).
- Produces : nouveaux défauts de `TideRouting` (`l_max`, `reinjection_schedule_s`, `enable_transitivity`) dont dépendent Tasks 3–6.

- [ ] **Step 1: Lancer la combinaison**

`$SCRATCH/combo.json` :
```json
{"tide": {
  "ref":              {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false},
  "fast":             {"l_max": 12, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": false},
  "fast+l14":         {"l_max": 14, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": false},
  "fast+l16":         {"l_max": 16, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": false},
  "fast+l20":         {"l_max": 20, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": false},
  "fast+trans":       {"l_max": 12, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": true},
  "fast+l14+trans":   {"l_max": 14, "reinjection_schedule_s": [60, 180, 600],   "enable_transitivity": true},
  "l14":              {"l_max": 14, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false},
  "l16":              {"l_max": 16, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false}
}}
```
Run : `python $SCRATCH/tune_tide.py $SCRATCH/combo.json tide_combo`
Expected : 36 runs (~5 min), puis le tableau trié.

- [ ] **Step 2: Choisir le gagnant (règle fixe)**

Parmi les lignes `PASS` dont `t x` ≤ 1,50, prendre le `dr` le plus haut. Si deux candidats sont à moins de 1 point d'écart, prendre celui qui change le moins de paramètres. Aucune ligne `PASS` → ne rien changer, noter le résultat dans le message de commit de la Step 6, et passer à la Task 3.

- [ ] **Step 3: Épingler le test sur l'ancien `l_max`**

Dans `tests/test_routing_tide.py`, remplacer :
```python
def test_initial_tokens_shrink_with_density():
    algo = TideRouting()
```
par :
```python
def test_initial_tokens_shrink_with_density():
    algo = TideRouting(l_max=12)
```
(`test_source_reinjects_tokens_without_ack` reste valable : à `now=400`, les deux calendriers donnent 2 réinjections, et 0+4+8=12 ≤ `l_max`.)

- [ ] **Step 4: Appliquer les défauts gagnants**

Dans `TideRouting.__init__`, changer uniquement les valeurs retenues, par exemple pour `fast+l16` :
```python
        l_max: int = 16,
        ...
        reinjection_schedule_s: Tuple[float, float, float] = (60.0, 180.0, 600.0),
```
Si la transitivité est retenue, `enable_transitivity: bool = True`.

- [ ] **Step 5: Tests**

Run : `pytest tests/test_routing_tide.py tests/test_routing_tide_g.py -v` puis `pytest`
Expected : tout PASS.

- [ ] **Step 6: Docs et commit**

Mettre à jour `docs/algorithmes/tide.md` (« reinjecte des jetons a 3, 6 et 20 min » → nouvelles valeurs ; transitivité si changée) et `README.md:281-288` de la même manière.
```bash
git add src/festival_ble_sim/routing/tide.py tests/test_routing_tide.py README.md docs/algorithmes/tide.md archives/*_tune_tide_combo.*
git commit -m "perf(tide): retune defaults from the 4-seed combination sweep"
```
Dans le corps du message : la ligne du gagnant (dr, d, ovh, E, t).

---

### Task 3: Défauts de TIDE-G sur la nouvelle base

**Files:**
- Modify : `src/festival_ble_sim/routing/tide_g.py` (`gps_for_relays`)
- Modify : `tests/test_routing_tide_g.py:127-134`
- Modify : `README.md:289-303`, `docs/algorithmes/tide_g.md`, `docs/TIDE-G.md:131,161`

**Interfaces:**
- Consumes : défauts de TIDE (Task 2).
- Produces : défaut `gps_for_relays` de `TideGRouting`.

- [ ] **Step 1: Lancer la comparaison**

`$SCRATCH/tide_g.json` :
```json
{"tide_g": {
  "ref":          {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false, "gps_for_relays": true},
  "new":          {"gps_for_relays": true},
  "new+nogpsrel": {"gps_for_relays": false}
}}
```
Run : `python $SCRATCH/tune_tide.py $SCRATCH/tide_g.json tide_g_base --baseline new`

- [ ] **Step 2: Décider (règle fixe)**

Si `new+nogpsrel` a `d` ≥ −1,0 (perte inférieure à 1 point en moyenne vs `new`) → nouveau défaut `gps_for_relays=False`. Sinon, garder `True` et noter dans le commit que B3 reste ouvert (Task 5 ne le traite pas : le spec en fait une règle seulement dans ce cas, à rediscuter avec l'utilisateur).

- [ ] **Step 3: Épingler le test GPS (si le défaut change)**

Dans `tests/test_routing_tide_g.py`, `test_relays_pay_for_their_gps_fixes`, première construction :
```python
    algo = _algo_with([a, b], {2: [b], 3: [a]}, gps_current_ma=36.0, gps_for_relays=True)
```

- [ ] **Step 4: Appliquer**

`tide_g.py` : `gps_for_relays: bool = False,`

- [ ] **Step 5: Tests**

Run : `pytest tests/test_routing_tide_g.py -v` puis `pytest`
Expected : PASS (`test_small_festival_with_replies_produces_hinted_deliveries` doit toujours voir `gps_fixes > 0` : les porteurs de messages à indice prennent toujours des fixes).

- [ ] **Step 6: Docs et commit**

`docs/TIDE-G.md:131` : la variante devient le défaut, avec le chiffre mesuré (énergie ×…, livraison …). Tableau `:161` : `gps_for_relays` passe à `False`. Même chose dans `README.md:303` et `docs/algorithmes/tide_g.md`.
```bash
git add src/festival_ble_sim/routing/tide_g.py tests/test_routing_tide_g.py README.md docs/TIDE-G.md docs/algorithmes/tide_g.md archives/*_tune_tide_g_base.*
git commit -m "perf(tide_g): GPS fixes only for holders of hinted messages by default"
```

---

### Task 4: B1 — pas de spray vers un contact trop dense

**Files:**
- Modify : `src/festival_ble_sim/routing/tide.py` (`__init__`, branche `tokens > 1` de `decide`)
- Test : `tests/test_routing_tide.py`

**Interfaces:**
- Consumes : `TideRouting._density: Dict[int, float]` (EWMA déjà calculée dans `on_tick`).
- Produces : paramètre `spray_density_max: Optional[float] = None`.

- [ ] **Step 1: Test qui échoue**

Ajouter à `tests/test_routing_tide.py` :
```python
def test_spray_skips_contacts_in_a_crowd_but_islands_still_pass():
    a, b, d = _node(1), _node(2), _node(99)
    algo = _algo_with([a, b, d], {1: [b], 2: [a]}, election=False, spray_density_max=5.0)
    msg = _msg()
    a.store_message(msg)
    algo._density[2] = 6.0
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE
    algo._density[2] = 4.0
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.FORWARD

    algo._density[2] = 6.0
    algo._neighbor_ids[2] = {1, 99}
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.FORWARD
```

- [ ] **Step 2: Vérifier l'échec**

Run : `pytest tests/test_routing_tide.py::test_spray_skips_contacts_in_a_crowd_but_islands_still_pass -v`
Expected : FAIL, `TypeError: __init__() got an unexpected keyword argument 'spray_density_max'`

- [ ] **Step 3: Implémenter**

Dans la signature, après `energy_factor: bool = True,` :
```python
        spray_density_max: Optional[float] = None,
```
Dans le corps : `self._spray_density_max = spray_density_max`. Dans `decide`, remplacer :
```python
        if tokens > 1:
            if not self._spray_ok(message, holder, contact, now):
                return RoutingDecision.IGNORE
```
par :
```python
        if tokens > 1:
            # Crowded contacts lose most sprays to hidden-terminal collisions.
            if self._spray_density_max is not None and self._density.get(contact.id, 0.0) > self._spray_density_max:
                return RoutingDecision.IGNORE
            if not self._spray_ok(message, holder, contact, now):
                return RoutingDecision.IGNORE
```

- [ ] **Step 4: Vérifier**

Run : `pytest tests/test_routing_tide.py -v` → PASS.

- [ ] **Step 5: Ablation**

`$SCRATCH/b1.json` (`ref` = anciens défauts, `base` = nouveaux défauts) :
```json
{"tide": {
  "ref":   {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false},
  "base":  {},
  "d10":   {"spray_density_max": 10.0},
  "d20":   {"spray_density_max": 20.0},
  "d40":   {"spray_density_max": 40.0}
}}
```
Run : `python $SCRATCH/tune_tide.py $SCRATCH/b1.json b1_density --baseline base`

- [ ] **Step 6: Décider et committer**

Une ligne `dXX` en `PASS` → défaut `spray_density_max` = la meilleure valeur, ajouter une puce dans `docs/algorithmes/tide.md` (« pas de spray vers un contact de densité > X ») et `README.md:274-288`, puis :
```bash
git add src/festival_ble_sim/routing/tide.py tests/test_routing_tide.py README.md docs/algorithmes/tide.md archives/*_tune_b1_density.*
git commit -m "perf(tide): skip sprays towards crowded contacts"
```
Aucune ligne `PASS` → `git checkout src/festival_ble_sim/routing/tide.py tests/test_routing_tide.py`, puis committer uniquement l'archive :
```bash
git add archives/*_tune_b1_density.*
git commit -m "chore(archives): B1 density-capped spray rejected by ablation"
```

---

### Task 5: B2 — une seule copie d'île par message et par tick

**Files:**
- Modify : `src/festival_ble_sim/routing/tide.py` (`__init__`, branche îles de `decide`, `on_forward`)
- Test : `tests/test_routing_tide.py`

**Interfaces:**
- Consumes : branche `island` de `decide`, `on_forward` (raison `"island"`).
- Produces : paramètre `single_island_copy: bool = False` ; état `self._island_tick: Dict[int, float]` (msg_id → dernier tick d'une copie d'île).

- [ ] **Step 1: Test qui échoue**

```python
def test_single_island_copy_per_message_per_tick():
    a, b, c, d = _node(1), _node(2), _node(3), _node(99)
    algo = _algo_with([a, b, c, d], {1: [b, c], 2: [a, d], 3: [a, d], 99: [b, c]}, single_island_copy=True)
    algo._is_relay = {1: True, 2: False, 3: False, 99: False}
    algo._last_relay_seen.update({2: 1.0, 3: 1.0})
    msg = _msg()
    a.store_message(msg)
    assert _forward(algo, msg, a, b) is not None
    assert algo.decide(msg, a, c, 1.0) is RoutingDecision.IGNORE
    algo.on_tick(2.0, {1: [b, c], 2: [a, d], 3: [a, d], 99: [b, c]})
    algo._is_relay = {1: True, 2: False, 3: False, 99: False}
    assert _forward(algo, msg, a, c, now=2.0) is not None
```
(Une fois l'île déjà servie, `c` est un simple membre : le reste de `decide` renvoie `IGNORE`.)

- [ ] **Step 2: Vérifier l'échec**

Run : `pytest tests/test_routing_tide.py::test_single_island_copy_per_message_per_tick -v`
Expected : FAIL, `TypeError: ... unexpected keyword argument 'single_island_copy'`

- [ ] **Step 3: Implémenter**

Signature : `single_island_copy: bool = False,` ; corps : `self._single_island_copy = single_island_copy` et `self._island_tick: Dict[int, float] = {}`. Dans `decide`, remplacer :
```python
        if self._islands and message.dst_id in self._neighbor_ids.get(contact.id, ()):
```
par :
```python
        if (
            self._islands
            and message.dst_id in self._neighbor_ids.get(contact.id, ())
            and not (self._single_island_copy and self._island_tick.get(message.msg_id) == now)
        ):
```
Dans `on_forward`, branche `if reason == "island":`, avant `return` :
```python
            self._island_tick[message.msg_id] = self._now
```

- [ ] **Step 4: Vérifier**

Run : `pytest tests/test_routing_tide.py -v` → PASS.

- [ ] **Step 5: Ablation**

`$SCRATCH/b2.json` :
```json
{"tide": {
  "ref":    {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false},
  "base":   {},
  "single": {"single_island_copy": true}
}}
```
Run : `python $SCRATCH/tune_tide.py $SCRATCH/b2.json b2_island --baseline base`

- [ ] **Step 6: Décider et committer**

`single` en `PASS` → défaut `True`, puce dans `docs/algorithmes/tide.md` (« ilots : une seule copie par message et par tick ») et `README.md`, commit `perf(tide): one island copy per message per tick` avec l'archive. Sinon, retirer le code (`git checkout` des deux fichiers) et committer l'archive seule : `chore(archives): B2 single island copy rejected by ablation`.

---

### Task 6: Validation finale

**Files:**
- Archive : `archives/<stamp>_tune_validation.*`, `archives/<stamp>_tune_noreply.*`

**Interfaces:**
- Consumes : défauts finaux de `TideRouting` / `TideGRouting` (Tasks 2–5).

- [ ] **Step 1: Run complet (seed 42)**

`$SCRATCH/validation.json` :
```json
{"tide":   {"ref": {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false}, "new": {}},
 "tide_g": {"ref": {"l_max": 12, "reinjection_schedule_s": [180, 360, 1200], "enable_transitivity": false, "gps_for_relays": true}, "new": {}}}
```
Si Tasks 4/5 ont changé un défaut, ajouter au `ref` l'ancienne valeur (`"spray_density_max": null`, `"single_island_copy": false`).
Run (en arrière-plan, plusieurs heures possibles) :
`python $SCRATCH/tune_tide.py $SCRATCH/validation.json validation --seeds 42 --n 4000 --duration 3600 --workers 4`
Expected : `new` en `PASS` pour `tide` et pour `tide_g` (ici « même signe » = un seul seed). Rapporter aussi `t x`.

- [ ] **Step 2: Contrôle sans réponses**

Run : `python $SCRATCH/tune_tide.py $SCRATCH/validation.json noreply --reply 0.0`
Expected : `new` a `d` ≥ −1,0 pour les deux algos (pas de régression quand il n'y a pas d'indices).

- [ ] **Step 3: Commit**

```bash
git add archives/*_tune_validation.* archives/*_tune_noreply.*
git commit -m "chore(archives): full-scale validation of the retuned TIDE/TIDE-G"
```
Si l'un des deux contrôles échoue : ne pas committer de conclusion. Rapporter les chiffres à l'utilisateur et s'arrêter là.
