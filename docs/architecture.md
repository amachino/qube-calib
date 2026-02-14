# qubecalib Runtime Architecture

This document describes the runtime-oriented module layout used by `qubecalib`
for quelware 0.10 integration.

## Design Goals

- Keep the `qubex -> qubecalib` public API stable.
- Isolate hardware-session runtime internals from API facade code.
- Minimize import cycles and make class ownership explicit.
- Keep conversion logic testable without touching hardware.

## Module Responsibilities

- `src/qubecalib/qubecalib.py`
  - Backward-compatible public export module.
  - Re-exports `QubeCalib`, `Sequencer`, `Converter`, `Executor`, `BoxPool`, and related types.
- `src/qubecalib/facade.py`
  - Implementation of high-level orchestration API (`QubeCalib`).
- `src/qubecalib/runtime/box_pool.py`
  - Hardware box registry, clock-master wiring, and per-box cache state.
- `src/qubecalib/runtime/executor.py`
  - Command queue and step-wise execution runtime.
- `src/qubecalib/runtime/converter.py`
  - Sampled-sequence to hardware-setting conversion (`CaptureParam` / `WaveSequence`).
- `src/qubecalib/runtime/commands.py`
  - Command primitives and runtime config accessors (`Command`, `RfSwitch`, `PortConfigAcquirer`).
- `src/qubecalib/runtime/sequencer_core.py`
  - Sequencer execution workflow (setting generation, trigger selection, capture parsing).
- `src/qubecalib/runtime/sequencer.py`
  - Compatibility re-exports for legacy import paths.

## Compatibility Rules

- Keep `qubecalib.qubecalib` import paths valid for `qubex`.
- Treat `runtime/*` internal organization as refactorable.
- Add regression tests when moving classes between modules.

## Validation Pipeline

Run from workspace root:

```bash
uv run ruff check src tests packages/qube-calib/src
uv run pyright
uv run pytest -q
```
