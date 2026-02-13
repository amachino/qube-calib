"""QuEL1 driver exports for qubecalib."""

__all__ = [
    "Action",
    "AwgId",
    "AwgSetting",
    "NamedBox",
    "Quel1System",
    "RunitId",
    "RunitSetting",
    "TriggerSetting",
]


def __getattr__(name: str):
    if name in __all__:
        from .driver import (
            Action,
            AwgId,
            AwgSetting,
            NamedBox,
            Quel1System,
            RunitId,
            RunitSetting,
            TriggerSetting,
        )

        exported = {
            "Action": Action,
            "AwgId": AwgId,
            "AwgSetting": AwgSetting,
            "NamedBox": NamedBox,
            "Quel1System": Quel1System,
            "RunitId": RunitId,
            "RunitSetting": RunitSetting,
            "TriggerSetting": TriggerSetting,
        }
        return exported[name]
    raise AttributeError(name)
