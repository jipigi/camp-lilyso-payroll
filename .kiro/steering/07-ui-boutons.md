# Règle 07 — Boutons primaires et secondaires (UI)

**Statut :** guide de travail
**Portée :** `app/pages_ui/**`

## Principe

Chaque écran de l'Interface_Streamlit distingue visuellement au plus
**une action principale** (bouton primaire) des actions secondaires
(boutons secondaires), pour guider l'opérateur vers l'action attendue
sans l'exposer à un choix ambigu entre plusieurs boutons de même poids
visuel.

## Visuels

| Rôle | Visuel | Usage |
|---|---|---|
| **Primaire** | fond foncé `#1f2c3b`, texte blanc `#FFFFFF` | l'action principale de l'écran — celle que l'opérateur vient chercher (ex. « Assembler la paie », « Enregistrer la paie », « Imprimer ») |
| **Secondaire** | visuel neutre par défaut de Streamlit (fond clair, bordure) | actions de moindre importance, peu fréquentes, ou de correction (ex. « Annuler », « Corriger cette paie ») |

Le bouton primaire est configuré une fois pour toute l'application via
le thème Streamlit (`.streamlit/config.toml::[theme].primaryColor =
"#1f2c3b"`) — tout `st.button(..., type="primary")` ou
`st.form_submit_button(..., type="primary")` hérite automatiquement de
ce visuel, sans CSS additionnel. Le visuel secondaire est le
comportement par défaut de `st.button` (`type="secondary"`, valeur
implicite si `type` est omis).

## Application

```python
# Action principale de l'écran
st.button("Assembler la paie", type="primary")

# Action secondaire (correction, annulation, navigation de repli)
st.button("Corriger cette paie", type="secondary")
st.button("Annuler")  # type="secondary" est la valeur par défaut
```

## Cas hors widgets natifs Streamlit

Un bouton qui doit déclencher un comportement JavaScript pur (ex. commande
d'impression du navigateur, `window.print()`) ne peut pas être un
`st.button` — Streamlit ne fournit aucun mécanisme pour exécuter du
JavaScript au clic d'un widget natif, et `st.markdown(...,
unsafe_allow_html=True)` assainit (DOMPurify) tout HTML injecté et
retire les attributs `onclick`. Dans ce cas :

- utiliser `st.components.v1.html(...)` (rendu dans un `<iframe>` non
  assaini) pour le bouton HTML/JS,
- répliquer le visuel primaire/secondaire en CSS inline sur ce bouton
  (les classes générées par le thème Streamlit ne sont pas accessibles
  depuis l'``<iframe>`` isolé du composant),
- documenter ce choix dans le module concerné (voir
  `app/pages_ui/bulletin_paie.py::_BOUTON_IMPRIMER_HTML` pour un
  exemple appliqué).

## Interdiction

- Ne jamais utiliser `type="primary"` pour plus d'une action par écran
  (perd la valeur de guidage du visuel).
- Ne jamais reproduire les couleurs primaires/secondaires en dur dans
  un module (`app/pages_ui/**`) pour un `st.button` natif — le thème
  centralisé (`.streamlit/config.toml`) est la source unique de vérité
  pour les widgets natifs. Le CSS inline n'est justifié que pour les
  boutons HTML/JS hors widgets natifs (voir section précédente).
