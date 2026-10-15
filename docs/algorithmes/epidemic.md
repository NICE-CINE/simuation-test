# `epidemic` — inondation naive

Fichier : `src/festival_ble_sim/routing/epidemic.py`
Spec : `docs/algorithmes/specs/EPIDEMIC.md`

## Principe

A chaque contact, le porteur transmet tout message que le voisin n'a pas
encore. C'est l'algorithme de reference : borne haute d'overhead et, en
theorie, borne basse de latence.

## Diagramme

Decision prise pour chaque message du porteur a chaque contact :

```mermaid
flowchart TD
    A["Contact entre porteur et voisin"] --> B{"Voisin = destination ?"}
    B -- oui --> L["Livraison (moteur)"]
    B -- non --> C{"Voisin a deja le message ?"}
    C -- oui --> I["IGNORE"]
    C -- non --> F["FORWARD : copie chez le voisin"]
```

## Forces

- Trivial (une condition), aucun etat, aucun parametre.
- Latence minimale tant que le reseau n'est pas sature : explore tous les
  chemins en parallele.
- Sert de reference pour mesurer ce que les autres algorithmes economisent.

## Faiblesses

- Overhead enorme : chaque message finit copie chez presque tout le monde,
  ce qui sature batterie, buffers et canal radio.
- En foule dense, la saturation se retourne contre lui : evictions de
  buffer et collisions radio font chuter le taux de livraison.
- Aucun nettoyage apres livraison : les copies continuent de circuler.

## References

Origine : Algorithme de la litterature, reproduit sans ajout (ecarts dans la spec, §6).

- A. Vahdat, D. Becker, *Epidemic Routing for Partially-Connected Ad Hoc Networks*, rapport technique CS-2000-06, Duke University, 2000. — article d'origine (summary vectors, compteur de sauts).
- X. Zhang, G. Neglia, J. Kurose, D. Towsley, *Performance Modeling of Epidemic Routing*, Computer Networks 51(10), 2007. — modele analytique du routage epidemique et de ses variantes.
