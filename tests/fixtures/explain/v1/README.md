# Stage 1 explanation report fixtures

These synthetic reports come from `explain.py` at commit `b8c8bcd3d4c6c16c66e7027acfb96bb471054cb3`.
They use the three-entity dictionary in `tests/conftest.py` with the local source and disambiguation rules.
The fixture covers these cases:

- Default output
- Canonical filtering
- Suppressed candidates
- Two context lengths

Offsets refer to the preprocessed body, not original-file evidence locators.
The reports contain no private corpus data.
