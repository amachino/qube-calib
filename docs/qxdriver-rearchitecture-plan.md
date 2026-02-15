# qxdriver_quel Re-Architecture Plan

This document records the current architecture and the guardrails for further refactoring.

## Contract Boundary

The only supported contract for `qubex` is `qxdriver_quel.compat`.

- Required symbol names are defined by `src/qubex/backend/quel1/quel1_driver_loader.py` (`_SYMBOL_IMPORT_PATHS`).
- Exported symbols must satisfy `src/qubex/backend/quel1/quel1_driver_protocols.py`.

Policy:

- Keep compatibility only at `qxdriver_quel.compat`.
- Do not keep compatibility aliases for any other historical import path.

## Current Directory Layout

```text
src/qxdriver_quel/
  compat/
    __init__.py
    exports.py
    qubex_contract.py
  qubecalib.py
  driver/
    __init__.py
    common.py
    single.py
    multi.py
    compat.py
  tool/
    __init__.py
    common.py
    skew.py
  pulse/
    __init__.py
    core.py
    models.py
    numeric.py
    tree.py
  e7awg/
    __init__.py
    compat.py
    utils.py
  clockmaster/
    __init__.py
    compat.py
  sysconf/
    __init__.py
    db.py
    models.py
    resource_map.py
  runtime/
    box_pool.py
    commands.py
    converter.py
    executor.py
    sequencer.py
    sequencer_core.py
```

## Ownership

- `compat/`
  - Sole qubex-facing compatibility layer.
  - Central symbol table lives in `compat/exports.py`.
- `qubecalib.py`
  - Public orchestration API (`QubeCalib`) and runtime re-exports used by compat.
- `driver/`, `tool/`
  - Direct QuEL1 action and tooling implementations.
- `pulse/`
  - Sequence DSL and sampled-sequence models.
- `e7awg/`
  - Legacy e7-compatible data structures and conversion utilities.
- `clockmaster/`
  - Clockmaster/sequencer client compatibility wrappers.
- `sysconf/`
  - System configuration DB/models and target resource mapping.
- `runtime/`
  - Sequencing runtime and execution mechanics.

## Review Checklist

- Is the change outside `compat/` adding contract-surface behavior? If yes, reject.
- Are `compat` export names unchanged unless intentionally coordinated with qubex?
- Do tests avoid depending on qxdriver internal module paths from qubex side?
- Do `make check` and `make test` pass after the change?
