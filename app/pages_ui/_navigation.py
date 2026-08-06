"""Registre des objets ``st.Page`` partagés entre ``app/main.py`` et les
modules de ``app/pages_ui/**`` (bug UI corrigé après livraison).

``st.switch_page`` exige l'objet ``StreamlitPage`` d'origine lorsqu'une
page est définie par un *callable* (comme c'est le cas ici — chaque page
est ``<module>.render``, jamais un fichier ``.py`` autonome) : passer un
chemin de fichier en chaîne échoue dans ce cas précis (documentation
Streamlit, ``st.switch_page`` — « To switch to a page defined by a
callable, you must use a Page object »).

**Patron registre, sans import circulaire** : ce module ne connaît lui-
même aucun module de rendu — ``app/main.py`` (le point d'entrée,
exécuté en premier par ``streamlit run``) construit les quatre objets
``st.Page`` puis les enregistre ici via :func:`configurer_pages`, avant
d'appeler ``navigation.run()``. Les modules de rendu qui doivent
naviguer vers une autre page (ex. ``tableau_de_bord.py``) importent ce
module et lisent ses attributs **au moment de l'appel** (à l'intérieur
d'une fonction, jamais au niveau module) — par construction, cet appel
ne peut survenir qu'après l'exécution de ``app/main.py``, donc après
:func:`configurer_pages`.

Couche de rendu (``app/pages_ui/``) : ce module ne contient aucune
logique de rendu lui-même — un simple registre partagé.
"""

from __future__ import annotations

from typing import Any

#: Attributs peuplés par :func:`configurer_pages`, appelée une seule
#: fois par ``app/main.py`` avant ``navigation.run()``. ``None`` tant
#: que ``app/main.py`` n'a pas encore exécuté cet appel — ne devrait
#: jamais être lu à ce stade (l'exécution normale de l'application
#: garantit l'ordre décrit ci-dessus).
page_tableau_de_bord: Any = None
page_nouvel_employe: Any = None
page_fiche_employe: Any = None
page_formulaire_paie: Any = None
page_historique: Any = None


def configurer_pages(
    *,
    tableau_de_bord: Any,
    nouvel_employe: Any,
    fiche_employe: Any,
    formulaire_paie: Any,
    historique: Any,
) -> None:
    """Enregistre les cinq objets ``st.Page`` construits par ``app/main.py``.

    Appelée une seule fois, avant ``navigation.run()`` — voir docstring
    de module pour la garantie d'ordre d'exécution.
    """
    global \
        page_tableau_de_bord, \
        page_nouvel_employe, \
        page_fiche_employe, \
        page_formulaire_paie, \
        page_historique
    page_tableau_de_bord = tableau_de_bord
    page_nouvel_employe = nouvel_employe
    page_fiche_employe = fiche_employe
    page_formulaire_paie = formulaire_paie
    page_historique = historique
