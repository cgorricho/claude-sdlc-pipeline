# Deferred Work

## From Story 1 — Repository Scaffold

- **Stale command references in docstrings/messages**: 15+ references to `python automation/auto_story.py` in `orchestrator.py`, `prompts.py`, and `config.py` docstrings/user messages. Should be updated to `csdlc run` when Story 4 refactors the orchestrator.
- **sys.path.insert hacks in test files**: 8 test files have `sys.path.insert(0, ...)` from the old non-package structure. Now redundant with pip install. Should be removed to validate the import system properly. Can be cleaned up alongside any story that touches test files.

## From Story 3 — CLI Entry Point

- **Stale `auto_story.py` docstring in orchestrator.py**: Module docstring (lines 1-23) still references `auto_story.py` and `python automation/auto_story.py --story 1-3`. Should be updated to reference `csdlc run` when Story 4 refactors the orchestrator.
