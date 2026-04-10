# Native vs CadQuery

- Default to Articraft-native abstractions for articulated structure, placements, tests, and straightforward geometry.
- Reach for CadQuery when shells, local cut geometry, smooth transitions, or precise construction history are easier to express at the lower level.
- Mixing native Articraft and CadQuery-backed geometry in one artifact is allowed when it produces a clearer, more realistic model.
- Keep units in meters by the time geometry reaches Articraft export helpers.
