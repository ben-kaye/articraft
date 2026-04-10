# Native vs CadQuery

- Default to Articraft-native abstractions for articulated structure, placements, tests, and straightforward geometry.
- Reach for CadQuery when shells, local cut geometry, smooth transitions, precise construction history, or richer low-level shape composition make the model clearer.
- Mixing native Articraft geometry helpers with CadQuery-backed meshes in one artifact is allowed when it produces a more realistic result.
- Keep units in meters by the time geometry reaches Articraft export helpers.
