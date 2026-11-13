# Lookup compatibility fixtures

The cases and alias dictionary come from `link.py lookup` at commit `037d64c442f95c99aa87b681d037bdfe5af64c5a`.
They use the synthetic dictionary in `tests/conftest.py`.
The `{PAGE}` placeholder replaces the absolute fixture path. Tests restore the native path before comparing reports.
The cases cover canonical names and English aliases. They also cover Unicode names, lowercase fallback, and missing names.
