# Algorithmes de routage

Presentation de chaque algorithme de `src/festival_ble_sim/routing/`, avec
ses forces et faiblesses dans le contexte du simulateur (festival, BLE
opportuniste, bornes optionnelles avec backhaul).

Les chiffres cites viennent de `archives/2026-09-28-comparaison.csv`
(un seul seed, colonnes `delivery_ratio`, `avg_latency_s`, `overhead`,
`total_energy_consumed_mah`) : ils donnent un ordre de grandeur, pas une
conclusion statistique. Relancer `scripts/compare_algorithms.py` avec
plusieurs seeds avant de trancher.

| Algo | Livraison sans / avec bornes | Latence moy. (s) | Overhead | Energie relative |
|---|---|---|---|---|
| `epidemic` | 29 % / 35 % | ~500 | ~10 000 | max |
| `spray_wait` | 30 % / 30 % | ~810 | ~24 | ~45 % |
| `prophet` | 36 % / 35 % | ~1 045 | ~230 | ~94 % |
| `beacon_priority` | 29 % / 31 % | ~525 | ~9 700 | max |
| `dasfv` | 38 % / 40 % | ~795 | ~172 | ~93 % |
| `gossip_a` | 43 % / 49 % | ~590 | ~2 550 | max |
| `bubble_f` | 19 % / 20 % | ~890 | ~40 | ~17 % |

Rappel : les couches de realisme du moteur (contention, collisions, TTL en
sauts, outage par shadowing, backhaul des bornes, voir `CLAUDE.md`)
s'appliquent a tous les algorithmes de la meme facon ; ce document ne
decrit que la decision de routage.

---

## `epidemic` — inondation naive

**Principe.** A chaque contact, le porteur transmet tout message que le
voisin n'a pas encore. C'est la reference : borne haute d'overhead et, en
theorie, borne basse de latence.

**Forces**
- Trivial (une condition), aucun etat, aucun parametre.
- Latence la plus basse quand le reseau n'est pas sature : explore tous
  les chemins en parallele.
- Reference utile pour mesurer ce que les autres algos economisent.

**Faiblesses**
- Overhead enorme (~10 000 transmissions par message livre) : batterie,
  buffers et canal radio satures.
- En foule dense, la saturation se retourne contre lui : evictions de
  buffer massives et pertes par collision, d'ou un taux de livraison
  *inferieur* a des algos bien plus economes.
- Aucun mecanisme de nettoyage apres livraison : les copies continuent de
  circuler.

---

## `spray_wait` — Spray and Wait binaire

**Principe.** Chaque message nait avec `L` jetons (`--spray-initial-copies`,
defaut 8). Lors d'un forward, le porteur garde la moitie et donne l'autre
(`on_forward`). Avec un seul jeton, le porteur passe en phase *wait* : il ne
transmet plus qu'a la destination elle-meme.

**Forces**
- Overhead borne et previsible (≤ `L` copies par message) : ~24 contre
  ~10 000 pour `epidemic`, pour un taux de livraison comparable.
- Energie divisee par ~2 par rapport a l'inondation.
- Aucun etat global, un seul parametre, comportement facile a raisonner.

**Faiblesses**
- Aveugle : distribue ses copies au premier venu, sans savoir qui a une
  chance de croiser la destination.
- Phase wait longue : latence nettement plus elevee (~800 s).
- `L` fixe, independant de la densite : trop peu en zone clairsemee, trop
  en zone dense.
- N'exploite pas les bornes (resultat identique avec ou sans).

---

## `prophet` — routage probabiliste PRoPHET

**Principe.** L'instance partagee maintient une predictabilite de
rencontre `P(a, b)` par paire de noeuds : augmentee a chaque rencontre,
vieillie exponentiellement (`gamma`) avec le temps, et optionnellement
transitive (`enable_transitivity`, desactivee par defaut). Un message est
transmis seulement si le voisin a une meilleure predictabilite vers la
destination que le porteur.

**Forces**
- Oriente : les copies vont vers les noeuds qui croisent souvent la
  destination, d'ou un meilleur taux de livraison que `spray_wait`.
- Overhead modere (~230) sans aucun budget de copies explicite.
- Tire parti des habitudes de deplacement (ex. mobilite `poi`).

**Faiblesses**
- Demarrage a froid : tant que l'historique est vide, peu de forwards ;
  latence la plus elevee du lot (~1 045 s).
- Pas de borne sur le nombre de copies : un gradient bruite peut quand
  meme repliquer beaucoup.
- Avec `random_waypoint`, les rencontres sont peu repetitives et la
  predictabilite porte peu d'information.
- La transitivite parcourt toute la table : couteuse a grande echelle.
- N'exploite pas specifiquement les bornes.

---

## `beacon_priority` — priorite aux bornes

**Principe.** Inondation epidemique entre telephones jusqu'a ce qu'une
copie atteigne une borne ; le message est alors marque `reached_beacon`
et les telephones arretent de le propager, le backhaul des bornes prenant
le relais.

**Forces**
- Tres simple, exploite directement l'infrastructure.
- Gain de livraison visible avec bornes (29 % → 31 %) et reduction de
  l'inondation une fois le message pris en charge.

**Faiblesses**
- Sans borne, c'est exactement `epidemic` (memes resultats), avec les
  memes defauts de saturation.
- Le marquage ne coupe que les copies qui ont vu une borne : les autres
  continuent d'inonder, l'overhead reste proche d'`epidemic`.
- Depend du nombre et du placement des bornes.

---

## `dasfv` — DASF-V (Density-Aware Spray-and-Focus + purge)

**Principe.** Version reduite au niveau reseau (pas de crypto, GATT, SOS,
epoques ; voir l'en-tete de `routing/dasfv.py`) :
- budget de copies initial adapte a la densite locale (entre `k_min` et
  `l_max`, reference `l_base`) ;
- phase *spray* (division des jetons) puis phase *focus* par gradient
  d'utilite PRoPHET ;
- relais a 2 sauts (voisin qui a vu la destination recemment) et
  heuristique de *mule* (noeud mobile a fort renouvellement de contacts) ;
- politique batterie : refus des pairs en batterie critique, evacuation
  acceleree depuis un porteur en batterie faible ;
- purge reseau-large des copies une fois le message livre.

**Forces**
- Bon compromis : livraison superieure a `spray_wait` et `prophet`
  (38-40 %) pour un overhead du meme ordre que `prophet` (~170).
- S'adapte a la densite au lieu d'un `L` fixe.
- Le mode focus evite la longue phase wait aveugle de Spray and Wait.
- La purge libere buffers et energie apres livraison.
- Protege les telephones en fin de batterie.

**Faiblesses**
- Beaucoup de parametres (une vingtaine) : calibration delicate, risque de
  sur-ajustement a un scenario.
- Les vues exactes de l'instance partagee (densite, 2 sauts, purge
  instantanee) sont optimistes par rapport a un vrai deploiement ou ces
  informations transitent par des balises/Bloom.
- Latence moyenne (~790 s) plus elevee que les approches par inondation.
- Energie proche de `prophet` : l'economie vient surtout de l'overhead,
  pas de la consommation radio de fond.

---

## `gossip_a` — GOSSIP-A (gossip probabiliste adaptatif)

**Principe.** Version reduite au niveau reseau (pas de crypto, etiquettes,
PoW, SOS) :
- probabilite de retransmission `p = clamp(C / densite, P_MIN, 1)`, tiree
  une fois par (message, pair) et par session ;
- inondation totale des `K_FLOOD` premiers sauts, borne `H_MAX` ;
- anti-entropie par resume Bloom (avec faux positifs simules) ;
- suppression par compteur (message deja vu chez `K_SUP` voisins) ;
- jetons de purge propages de proche en proche apres livraison ;
- budgets par session (octets, bundles) et eviction « plus repliques
  d'abord » (`choose_eviction`).

Les interrupteurs `adaptive`, `suppression`, `replicated_first_eviction`
permettent des ablations.

**Forces**
- Meilleur taux de livraison mesure (43 % sans bornes, 49 % avec) et
  latence parmi les plus basses (~560-620 s).
- Profite nettement des bornes.
- Densite-adaptatif : inonde en zone clairsemee, se retient en foule.
- L'eviction « plus repliques d'abord » protege les messages rares quand
  les buffers saturent.
- Seul algo complexe qui modelise des imperfections realistes (faux
  positifs Bloom, budgets de session).

**Faiblesses**
- Overhead eleve (~2 500) : 10 a 15 fois `dasfv`, meme s'il reste 4 fois
  sous `epidemic`.
- Energie au niveau d'`epidemic` : le gain de livraison se paie en
  batterie.
- Aleatoire (RNG propre, `seed`) : resultats plus variables d'un seed a
  l'autre, a verifier sur plusieurs runs.
- Nombreux parametres (`C`, `P_MIN`, `K_FLOOD`, `H_MAX`, `K_SUP`,
  fenetres, budgets).

---

## `bubble_f` — BUBBLE-F (routage social)

**Principe.** Inspire de BUBBLE Rap :
- communautes amorcees par un graphe d'amis genere au lancement (groupes
  de 2 a 8, 20 % d'utilisateurs sans ami), enrichies par SIMPLE
  (familiers apres 20 min de contact cumule, ajout par recouvrement,
  fusion) ;
- rangs global et local C-Window (4 fenetres de 30 min) ;
- budget de 8 jetons en division binaire : entrer dans la bulle du
  destinataire, sinon monter en rang global, puis en rang local a
  l'interieur ;
- relais a 2 sauts, replication anti-blocage apres 30 min sans progres,
  admission restreinte des buffers pleins a 80 %, epoques optionnelles.

Bloom, `rankCap`, SOS et RSSI ne sont pas modelises.

**Forces**
- De loin le plus econome : overhead ~40 et ~17 % de l'energie
  d'`epidemic`, aucune eviction de buffer.
- Pertinent des qu'il existe une vraie structure sociale (groupes d'amis
  qui se deplacent ensemble, habitues d'une scene).
- L'admission restreinte et l'anti-blocage evitent a la fois la
  saturation et les messages coinces indefiniment.

**Faiblesses**
- Pire taux de livraison mesure (~19-20 %) dans la configuration actuelle.
- Cause principale : avec `random_waypoint`, les amis ne se deplacent pas
  ensemble, donc les bulles ne correspondent a aucune proximite reelle.
  L'algo attend un modele de mobilite de groupe qui n'existe pas encore.
- Les rangs C-Window demandent du temps pour se construire (fenetres de
  30 min) : faible sur des runs courts.
- Le graphe d'amis est synthetique : les resultats dependent fortement de
  `group_size_range` et `no_friend_fraction`.
- Beaucoup de parametres et de mecanismes imbriques.

---

## En resume

- **Livraison maximale** : `gossip_a`, au prix de l'energie.
- **Meilleur compromis livraison / overhead** : `dasfv`.
- **Economie maximale** : `bubble_f` (a reevaluer avec une mobilite de
  groupe) puis `spray_wait` (simple et previsible).
- **References** : `epidemic` (borne haute d'overhead), `prophet`
  (routage probabiliste classique).
- **Infrastructure** : `beacon_priority` est l'approche la plus directe,
  mais `gossip_a` et `dasfv` tirent en pratique mieux parti des bornes.
