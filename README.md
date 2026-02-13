# qubecalib

`qubecalib` is a calibration and sequence-execution library for QuBE/QuEL systems.
It provides:

- System configuration modeling (`SystemConfigDatabase`)
- Pulse-sequence sampling (`neopulse`)
- Direct quelware 0.10 action execution (`instrument/quel/quel1/driver`)
- High-level orchestration (`QubeCalib`, `Executor`)

## Compatibility Policy

This package is maintained for `qubex -> qubecalib` integration.

- Public APIs used by `qubex` must remain backward compatible.
- Internal implementation may be refactored aggressively.
- quelware target: 0.10.x series.

## Installation

### Prerequisites

- Python 3.9+
- `pip` or `uv`

### Install from repository

```bash
pip install git+https://github.com/qiqb-osaka/qube-calib.git
```

Install a pinned tag:

```bash
pip install git+https://github.com/qiqb-osaka/qube-calib.git@x.y.z
```

## Development

From the workspace root:

```bash
uv run ruff check packages/qube-calib/src
uv run ruff format packages/qube-calib/src
uv run pyright packages/qube-calib/src
uv run pytest packages/qube-calib/tests/unit -q
```

Full workspace gates (if `qubex` is checked out together):

```bash
uv run ruff check src tests packages/qube-calib/src
uv run pyright
uv run pytest -q
```

## Project Layout

- `src/qubecalib/`: library sources
- `tests/`: unit tests
- `docs/`: usage notebooks and sample configs

## Related Projects

- `qube-server`: moved from historical `QubeServer.py` scope
  ([qiqb-osaka/qube-server](https://github.com/qiqb-osaka/qube-server))
