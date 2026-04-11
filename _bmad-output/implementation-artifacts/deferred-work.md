# Deferred Work

## From Story 1 — Repository Scaffold

- **Stale command references in docstrings/messages**: 15+ references to `python automation/auto_story.py` in `orchestrator.py`, `prompts.py`, and `config.py` docstrings/user messages. Should be updated to `csdlc run` when Story 4 refactors the orchestrator.
- **sys.path.insert hacks in test files**: 8 test files have `sys.path.insert(0, ...)` from the old non-package structure. Now redundant with pip install. Should be removed to validate the import system properly. Can be cleaned up alongside any story that touches test files.
