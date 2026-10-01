# NICE — Algorithmes de routage candidats et protocole de comparaison

Sep 30, 2026 · @Nils

## Contexte et exigences

Six algorithmes de routage sont comparés sur un même protocole de simulation, pour n'en garder qu'un seul dans NICE : une messagerie qui passe uniquement par un mesh Bluetooth formé des téléphones des festivaliers.

| Exigence | Valeur retenue |
| --- | --- |
| Cas d'usage | Festival, toutes tailles (\~2 000 à \~80 000 personnes) |
| Réseau | Mesh BLE composé uniquement des téléphones des utilisateurs, libres de se déplacer |
| Trafic | Unicast uniquement (groupes et broadcast hors périmètre pour l'instant) |
| Adoption | Visée \~100 % (intégration aux applis de festival), simulée à 100, 50 et 20 % d'adoption effective |
| Priorités | 1. taux de livraison, 2. latence, 3. batterie, sans surcharger le mesh |
| Latence | ≤ 2 min parfait · 2–5 min très bien · 5–10 min acceptable · > 10 min échec |
| Messages en retard | Toujours acheminés et livrés, marqués « en retard » avec leur âge |
| Localisation | Non utilisée (ni GPS, ni zones) |

L'adoption effective est simulée plus bas que 100 % car intégré à l'appli ne veut pas dire actif : Bluetooth coupé, permission refusée, mode économie d'énergie et limites d'iOS en arrière-plan réduisent la part de téléphones réellement joignables.

## Socle commun à tous les candidats

Tous les candidats partagent le même format de message, la même couche d'ACK et la même règle de retard. Seule la décision de routage change, ce qui rend la comparaison équitable.

### Format de message

| Champ | Taille | Rôle |
| --- | --- | --- |
| id | 16 o | Hash(src, seq, ts), sert à la déduplication |
| src, dst | 8 o chacun | Pseudonymes de routage (voir plus bas) |
| ts\_création | 8 o | Horodatage de l'émetteur |
| âge\_cumulé | 4 o | Somme des temps de séjour à chaque saut |
| sauts | 1 o | Nombre de sauts parcourus |
| jetons | 1 o | Copies autorisées (candidats à quota) |
| classe | 1 o | À l'heure ou en retard |
| signature | 64 o | Ed25519 de l'émetteur sur les champs immuables (id, src, dst, ts, charge utile) |
| charge utile | ≤ 1 ko | Chiffrée de bout en bout (X25519, ChaCha20-Poly1305) |

Les champs mutables (âge\_cumulé, sauts, jetons, classe) ne sont pas signés ; un relais malveillant peut les altérer, ce qui est traité dans la partie sécurité de TIDE.

### ACK et purge

- À la livraison, le destinataire émet un ACK : id du message, sa clé publique (32 o) et sa signature (64 o), soit \~112 o.
- Le pseudonyme étant dérivé de la clé publique, n'importe quel relais vérifie l'ACK sans annuaire.
- À chaque contact, les ACK s'échangent en premier. Un filtre de Bloom cumulatif indique lesquels demander.
- Un ACK valide fait supprimer la copie et refuser toute nouvelle copie du message.
- Cette couche est activée pour tous les candidats, références comprises. Sinon, elles seraient pénalisées en surcharge par un détail indépendant du routage.

### Âge et marquage « en retard »

- À la réception, âge = heure locale − ts\_création. Si cet âge et âge\_cumulé divergent de plus de 2 min, on retient âge\_cumulé, insensible au décalage d'horloge (principe du bloc d'âge du Bundle Protocol).
- Au-delà de 10 min, le message s'affiche marqué « en retard » avec son âge, par exemple « envoyé il y a 23 min ».
- Côté émetteur, sans ACK à 10 min, le message passe à « non confirmé » et continue sa route.
- Dans le réseau, un message de plus de 10 min passe en classe basse : transmis après les messages à l'heure, évincé en premier, mais jamais abandonné avant le TTL.

### Durée de vie et pseudonymes

- TTL dur de 2 h par défaut, pour que les buffers restent bornés. Il est testé à 30 min, 2 h et 6 h. Plafond de 20 sauts.
- Pseudonyme de routage = les 8 premiers octets du hash de la clé publique, avec une nouvelle paire de clés par festival.
- Il reste stable pendant l'événement, car les tables d'utilité en ont besoin. Ce n'est jamais le numéro de téléphone.

## Les candidats

Quatre références encadrent deux candidats : DASF-V et TIDE. Les références situent les candidats entre « tout copier » et « copier intelligemment ».

| Algo | Rôle | Principe | Paramètres (valeurs testées) |
| --- | --- | --- | --- |
| Epidemic (Vahdat & Becker, 2000) | Référence haute | À chaque contact, copie de tout message que l'autre n'a pas | Aucun, hors taille de buffer |
| Flooding géré (Bluetooth Mesh) | Référence industrie | Relais immédiat vers les voisins présents, cache des id déjà vus, pas de transport | TTL en sauts : 5 / 10 / 20 |
| Spray and Wait binaire (Spyropoulos et al., 2005) | Référence simple | L copies partagées par moitiés, puis attente de la rencontre directe | L : 4 / 8 / 16 |
| PRoPHETv2 (Grasic et al., 2011) | Référence utilité | Copie vers B si B a une meilleure prédictibilité de rencontre du destinataire | Valeurs par défaut de l'implémentation de référence |
| DASF-V | Candidat | Spray-and-focus sensible à la densité, ACK et purge vérifiables | À reporter depuis la spec DASF-V existante |
| TIDE | Candidat | Jetons pondérés par l'utilité, livraison directe dans les îlots, relais élus selon densité et batterie | Voir la section TIDE |

Epidemic, Spray and Wait et PRoPHET sont fournis avec The ONE ; la disponibilité de PRoPHETv2 dépend de la version. Le flooding géré, DASF-V et TIDE sont à implémenter.

## TIDE : spécification détaillée

TIDE livre directement dans les îlots de téléphones connectés, borne les copies par des jetons répartis selon l'utilité, et ne fait relayer qu'une fraction des téléphones, élue selon la densité et la batterie. Son nom résume ces quatre briques : Tokens, Islands, Density, Energy.

### État par nœud

- Table de rencontres : pour chaque pseudonyme X croisé, sa prédictibilité P(X) et l'heure de la dernière rencontre.
- Voisinage : voisins actuels et leurs propres voisins (vue à 2 sauts).
- Buffer : messages avec leurs jetons, leur classe et leur âge.
- Densité locale ρ : moyenne glissante du nombre de voisins distincts par fenêtre de scan.
- Énergie : niveau de batterie, en charge ou non, en mouvement ou non (capteur de mouvement significatif).
- Rôle : relais, membre ou feuille.

### Utilité d'un nœud X pour un destinataire d

```latex
U_X(d) = e_X \cdot \left[\, w \, P_X(d) + (1 - w) \, e^{-\Delta t_X(d) / \tau} \,\right]
```

- P\_X(d) est la prédictibilité PRoPHET (fréquence, vieillissement, transitivité). Elle capte les amis du destinataire.
- Δt\_X(d) est le temps depuis la dernière rencontre directe avec d. Il capte « je l'ai vu il y a 5 min ».
- e\_X est le facteur énergie : 1 en charge ou au-dessus de 50 %, puis linéaire jusqu'à 0,2 à 20 %.
- Valeurs de départ : w = 0,5, τ = 20 min, et pour PRoPHET P\_init = 0,75, β = 0,25, γ = 0,98 (papier original), à recalibrer.

### Rôles et élection des relais

| Rôle | Condition | Comportement |
| --- | --- | --- |
| Relais | Élu avec la probabilité p\_X | Porte et relaie les messages des autres |
| Membre | Non élu | Envoie, reçoit et livre dans l'îlot, mais ne porte pas les messages des autres |
| Feuille | Batterie sous 15 % | Scan minimal ; un relais voisin garde ses messages entrants (principe Friend / Low Power du Bluetooth Mesh) |

```latex
p_X = \min\left(1,\ \frac{\rho_{cible}}{\rho} \cdot \frac{e_X}{\bar{e}}\right)
```

- ρ\_cible = 15 relais à portée ; ē est le facteur énergie moyen des voisins, lu dans leurs annonces.
- Le tirage a lieu toutes les 5 min, et le rôle tourne pour répartir la consommation (principe de LEACH).
- Un relais sortant garde son rôle tant qu'il porte des messages d'autres nœuds.
- Un membre qui ne voit aucun relais pendant 30 s se comporte en relais.
- En zone clairsemée, ρ est sous ρ\_cible donc p = 1 : tout le monde relaie. Devant une scène à ρ = 200, p tombe à \~7 %.

### Découverte et annonces

- L'annonce BLE porte un ID éphémère (8 o, renouvelé toutes les 15 min), un digest du buffer et des ACK (4 o) et un octet d'état (rôle, énergie, tranche de densité).
- La correspondance ID éphémère → pseudonyme s'apprend à la première connexion et reste en cache jusqu'au renouvellement.
- On ne se connecte à un pair que si son digest a changé depuis la dernière synchro, ou s'il n'a jamais été synchronisé.
- Au plus K = 5 synchros par minute. Ordre de priorité : destinataires d'un message en buffer, pairs jamais synchronisés, puis relais au digest modifié.
- Intervalle d'annonce = 0,5 s × max(1, ρ/20), plafonné à 5 s, pour limiter les collisions sur les 3 canaux d'annonce.
- Scan actif (\~25 % du temps) si le nœud porte des messages ou bouge. Sinon veille (\~10 %) avec back-off Trickle : l'intervalle double tant que rien ne change, et revient au minimum à un nouveau voisin, message ou mouvement.
- Sur iOS en arrière-plan, l'annonce ne peut pas porter de données : digest et état se lisent par une courte lecture GATT.

### Décision par message

&#91;embedded content: décision par message au contact · 4 tests\]

Les jetons et la copie unique ne vont qu'aux relais ; un membre ne reçoit un message que s'il peut le livrer immédiatement.

Partage des jetons quand A (L jetons, utilité U\_A) rencontre un relais B :

```latex
k_B = \mathrm{clamp}\left(\mathrm{round}\left(L \cdot \frac{U_B}{U_A + U_B}\right),\ 1,\ L - 1\right)
```

Jetons initiaux selon la densité locale, avec ρ\_ref = 10 :

```latex
L_0 = \mathrm{clamp}\left(\mathrm{round}\left(12 \sqrt{\rho_{ref} / \rho}\right),\ 2,\ 12\right)
```

- On obtient 12 jetons à ρ = 10, 6 à ρ = 40 et 2 au-delà de ρ = 360.
- L'hystérésis δ = 0,05 évite que la copie unique fasse des allers-retours entre deux nœuds proches.
- Ordre de transmission au contact : ACK, messages pour B, messages propres, messages à l'heure par nombre de sauts croissant, puis messages en retard.

### Fiabilité : réinjection par la source

- La source garde une copie fantôme (0 jeton) jusqu'à l'ACK ou au TTL.
- Sans ACK, elle réinjecte L₀/2 jetons à 3 min, L₀ jetons à 6 min, puis L₀/2 à 20 min en classe basse.
- Les doublons éventuels sont éliminés à destination grâce à l'id.

### Anti-surcharge et buffer

- Buffer de 500 messages maximum par nœud, soit \~0,6 Mo.
- Au plus 30 messages en vol par émetteur dans un même buffer, contre le spam.
- Éviction dans cet ordre : acquittés, TTL dépassé, classe « en retard », puis copies à 1 jeton de plus faible utilité et de plus grand nombre de sauts. Jamais les messages propres.

### Sécurité du routage

- L'utilité annoncée est plafonnée à 1.
- Réputation locale : un pair dont les messages confiés ne donnent jamais d'ACK voit son utilité pondérée à la baisse.
- Les jetons ne sont pas signés : à la réception, ils sont plafonnés à 12.
- La phase à jetons garde plusieurs copies, donc un menteur isolé ne capte pas tout le trafic.

## Protocole de simulation

Chaque candidat tourne dans The ONE sur les mêmes 27 scénarios, avec 10 graines chacun, soit 1 620 simulations. Un modèle BLE et un modèle d'énergie sont ajoutés au simulateur, qui n'en a pas.

### Outil

- The ONE (Keränen et al., 2009), en Java. Le flooding géré, DASF-V et TIDE s'écrivent comme sous-classes de son routeur actif.
- The ONE ralentit fortement au-delà de quelques milliers de nœuds. Pour les grands festivals, on simule une zone représentative (fosse et abords d'une grande scène) à densité réelle.

### Modèle BLE

The ONE modélise un contact par une portée et un débit, sans découverte ni coût de connexion. Les hypothèses ci-dessous sont à calibrer sur appareils réels.

| Paramètre | Hypothèse de départ |
| --- | --- |
| Portée | 10 m en foule dense, 30 m en zone dégagée (le corps humain absorbe le 2,4 GHz) |
| Délai de découverte | Calculé à partir du cycle de scan et de l'intervalle d'annonce |
| Établissement de connexion | 0,5 à 2 s |
| Débit utile par lien | 20 ko/s |
| Connexions simultanées | 4 par téléphone |
| Collisions d'annonce | Probabilité de perte croissante avec le nombre d'annonceurs à portée |

### Modèle d'énergie

- Énergie = temps de scan × coût du scan + nombre d'annonces × coût d'une annonce + nombre de connexions × coût d'une connexion + octets échangés × coût par octet.
- Les coefficients sont mesurés sur 2 à 3 téléphones réels, Android et iOS, avant la campagne.
- Résultat en % de batterie par heure : moyenne et 95e centile par nœud, car les relais consomment plus que les autres.

### Mobilité festival

- Carte à zones : scènes (2 à 6 selon la taille), bars, sanitaires, entrée, camping.
- Programme horaire par scène. À la fin d'un set, une vague de déplacements part vers les autres scènes.
- Groupes d'amis de 3 à 6 personnes qui se déplacent ensemble et se séparent de temps en temps, cas typique d'usage de la messagerie.
- Marche à 0,5–1,5 m/s, ralentie en foule dense.
- Modèle de mouvement personnalisé, basé sur le mouvement sur carte avec points d'intérêt de The ONE.

### Trafic

- Unicast : 70 % des messages vers un membre du groupe d'amis, 30 % vers un autre contact tiré au hasard.
- En moyenne 1 message par utilisateur actif toutes les 10 min (processus de Poisson), avec des pics aux fins de concert.
- Charge utile de 100 o à 1 ko.

### Scénarios

| Dimension | Valeurs |
| --- | --- |
| Taille | Petit (\~2 000), moyen (\~20 000), grand (\~80 000, zone représentative) |
| Adoption effective | 100 %, 50 %, 20 % |
| Moment | Pendant un concert (dense et statique), changement de plateau (mouvement de masse), nuit au camping (clairsemé) |
| Durée | 2 h simulées, les 20 premières minutes exclues des mesures (remplissage des tables) |
| Répétitions | 10 graines par scénario, intervalles de confiance à 95 % |

## Métriques et règle de sélection finale

L'algo retenu est celui qui a le meilleur score S moyen, parmi ceux qui respectent un budget batterie et un plafond de surcharge dans tous les scénarios. S reprend directement tes seuils de latence.

```latex
S = \frac{1{,}0 \cdot n_{\le 2\,min} + 0{,}8 \cdot n_{2\text{–}5\,min} + 0{,}5 \cdot n_{5\text{–}10\,min}}{n_{envoyés}}
```

Un message livré après 10 min compte 0 dans S, mais il est compté dans le taux de livraison total.

| Métrique | Définition | Usage |
| --- | --- | --- |
| Score S | Formule ci-dessus | Critère principal |
| Livraison à 10 min | Livrés en 10 min ou moins / envoyés | Lecture de S |
| Livraison totale | Livrés avant le TTL, retards compris / envoyés | Départage |
| Latence | Médiane et 95e centile | Lecture |
| Surcharge | Transmissions / messages livrés | Contrainte |
| Énergie | % de batterie par heure, moyenne et 95e centile par nœud | Contrainte |
| Charge radio | Connexions par nœud et par minute, annonceurs à portée | Diagnostic de congestion |
| Évictions | Messages supprimés faute de place | Diagnostic de buffer |

Règle de sélection :

1. Écarter tout candidat dont le 95e centile d'énergie dépasse le budget B dans au moins un scénario.
2. Écarter tout candidat dont la surcharge dépasse le plafond O dans au moins un scénario.
3. Classer les candidats restants par S moyen sur les 27 scénarios.
4. Départager par le S du pire scénario, puis par la livraison totale.

Questions ouvertes : la valeur de B (par exemple 3 %/h, soit \~36 % sur une journée de 12 h), celle de O, et les poids 1 / 0,8 / 0,5 de S.

## Études d'ablation et de sensibilité

Chaque brique de TIDE est retirée une à une pour mesurer ce qu'elle apporte. Les paramètres clés sont ensuite balayés, pour vérifier que le classement ne tient pas à un réglage chanceux.

| Variante | Brique retirée | Ce qu'on vérifie |
| --- | --- | --- |
| Sans îlots | Livraison directe via un voisin du destinataire | Gain en latence en foule dense |
| Sans jetons pondérés | Partage par moitiés, comme Spray and Wait | Gain en livraison |
| Sans élection | Tout le monde relaie | Gain en énergie et en charge radio |
| Sans digest | Connexion à chaque rencontre | Gain en énergie en foule statique |
| Sans réinjection | Aucune réinjection par la source | Gain en livraison |
| Sans facteur énergie | e\_X = 1 pour tous | Répartition de la consommation entre nœuds |

Le balayage des paramètres tourne sur 3 scénarios (festival moyen, adoption 100 %, les trois moments), pour limiter le nombre de simulations.

| Paramètre | Valeurs testées |
| --- | --- |
| TTL | 30 min, 2 h, 6 h |
| ρ\_cible | 5, 15, 30 |
| Jetons initiaux maximum | 6, 12, 24 |
| τ | 5, 20, 60 min |
| w | 0 ; 0,5 ; 1 |
| K (synchros par minute) | 2, 5, 10 |

## À valider sur vrais appareils

Six hypothèses du modèle BLE peuvent renverser le classement. Elles se testent avant la campagne de simulation, sur 20 à 30 téléphones Android et iOS.

- [ ] Portée réelle en foule dense (corps entre les téléphones) et en zone dégagée
- [ ] Temps d'une connexion GATT complète, découverte des services comprise
- [ ] Nombre de connexions simultanées tenables par téléphone
- [ ] Découverte iOS–iOS et iOS–Android avec l'appli en arrière-plan
- [ ] Coûts énergétiques du scan, des annonces et des connexions
- [ ] Taux de perte d'annonces avec 20 à 30 téléphones proches

## Récapitulatif des paramètres

Valeurs de départ à reporter dans les fichiers de configuration de The ONE ; toutes sont à recalibrer après les tests sur appareils.

| Paramètre | Valeur de départ | Portée |
| --- | --- | --- |
| TTL dur | 2 h | Tous |
| Seuil « en retard » | 10 min | Tous |
| Plafond de sauts | 20 | Tous |
| w (poids fréquence / fraîcheur) | 0,5 | TIDE |
| τ (fraîcheur) | 20 min | TIDE |
| P\_init, β, γ (PRoPHET) | 0,75 ; 0,25 ; 0,98 | TIDE |
| Facteur énergie e\_X | 1 au-dessus de 50 %, 0,2 à 20 % | TIDE |
| Seuil feuille | 15 % de batterie | TIDE |
| ρ\_cible | 15 relais à portée | TIDE |
| Période d'élection | 5 min | TIDE |
| Repli membre vers relais | 30 s sans relais visible | TIDE |
| Renouvellement de l'ID éphémère | 15 min | TIDE |
| K | 5 synchros par minute | TIDE |
| Intervalle d'annonce | 0,5 à 5 s selon ρ | TIDE |
| Cycle de scan | \~25 % actif, \~10 % veille | TIDE |
| Jetons initiaux L₀ | 2 à 12 selon ρ (ρ\_ref = 10) | TIDE |
| Hystérésis δ | 0,05 | TIDE |
| Réinjections | À 3, 6 et 20 min | TIDE |
| Buffer | 500 messages | TIDE |
| Quota par émetteur | 30 messages | TIDE |
