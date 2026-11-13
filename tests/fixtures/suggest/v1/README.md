# Alias suggestion fixtures

The reports and ranked fields come from `suggest.py` at commit `26e8cfeeb8ee63b833e80026a9b9b0606a673e4d`.
They use the dictionary in `tests/conftest.py` with the local target and source corpus.
The target uses the existing frontmatter and fence preprocessing.
Document frequencies use complete source files, as the legacy implementation requires.
Snapshots cover the default limit and limits of three and zero.
All inputs are synthetic.
