# qxdriver_quel Architecture

This document describes the current `qxdriver_quel` architecture and the
compatibility contract used by `qubex`.

## Scope And Goals

- Keep the `qubex -> qxdriver_quel.compat` contract stable.
- Keep runtime internals (`runtime/*`, `driver/*`, `sysconf/*`) refactorable.
- Isolate hardware access from conversion logic to keep offline tests practical.

## Contract Boundary

The only supported integration surface for `qubex` is `qxdriver_quel.compat`.

- Required symbol names are defined by
  `src/qubex/backend/quel1/quel1_driver_loader.py` (`_SYMBOL_IMPORT_PATHS`).
- Symbol availability/alignment is checked by
  `src/qxdriver_quel/compat/qubex_contract.py`.
- Exported symbols are expected to satisfy protocols in
  `src/qubex/backend/quel1/quel1_qubealib_protocols.py`.

Policy:

- Keep compatibility only at `qxdriver_quel.compat`.
- Do not add compatibility aliases for historical internal module paths.

## Current Layout

```text
src/qxdriver_quel/
  compat/
    __init__.py
    exports.py
    qubex_contract.py
  qubecalib.py
  runtime/
    box_pool.py
    commands.py
    converter.py
    executor.py
    sequencer.py
    sequencer_core.py
  driver/
    common.py
    single.py
    multi.py
    compat.py
  sysconf/
    db.py
    models.py
    resource_map.py
  pulse/
    core.py
    models.py
    numeric.py
    tree.py
  e7awg/
    compat.py
    utils.py
  clockmaster/
    compat.py
  tool/
    common.py
    skew.py
```

## Runtime Responsibilities

- `compat/`
  - Sole `qubex`-facing compatibility layer.
  - Centralized export table and contract checks.
- `qubecalib.py`
  - Public orchestration API (`QubeCalib`) and runtime re-exports.
- `runtime/box_pool.py`
  - Hardware box lifecycle and box-config cache management.
- `runtime/commands.py`
  - Command primitives and port-config acquisition (`PortConfigAcquirer`).
- `runtime/converter.py`
  - Sampled sequence conversion into device-specific capture/gen settings.
- `runtime/sequencer_core.py`
  - Sequencer workflow: resource filtering, setting generation, trigger selection,
    capture-result parsing.
- `runtime/executor.py`
  - Execution runtime and command dispatch.

## Integration Notes

- `Sequencer` supports both paths:
  - boxpool path (`driver=None`)
  - direct driver path (`driver=Quel1System`)
- `PortConfigAcquirer` adjusts read-input sideband from corresponding read-output
  port only on the boxpool path.
- `qubex` may override sequencer methods to force the boxpool path for specific
  backward-compatibility behavior (for example, legacy R8 readout handling).
  This is an integration policy on `qubex` side, not a `qxdriver_quel.compat`
  contract change.

## Maintenance Rules

- Changes outside `compat/` must not alter the compatibility surface implicitly.
- If compat exports change, update both:
  - `compat/exports.py`
  - `compat/qubex_contract.py`
- Add regression tests when moving runtime classes or changing conversion logic.

## Validation

Run from workspace root:

```bash
uv run ruff check src tests packages/qxdriver-quel/src packages/qxdriver-quel/tests
uv run pyright
uv run pytest -q packages/qxdriver-quel/tests
```
