"""Direct driver exports for single/multi QuEL1 actions."""

__all__ = [
    "Action",
    "AwgId",
    "AwgSetting",
    "NamedBox",
    "Quel1PortType",
    "Quel1System",
    "RunitId",
    "RunitSetting",
    "TriggerSetting",
]


def __getattr__(name: str):
    if name == "Quel1PortType":
        from .single import Quel1PortType

        return Quel1PortType
    if name in {"NamedBox", "Quel1System"}:
        from .multi import NamedBox, Quel1System

        return {"NamedBox": NamedBox, "Quel1System": Quel1System}[name]
    if name in {
        "Action",
        "AwgId",
        "AwgSetting",
        "RunitId",
        "RunitSetting",
        "TriggerSetting",
    }:
        from .common import (
            Action,
            AwgId,
            AwgSetting,
            RunitId,
            RunitSetting,
            TriggerSetting,
        )

        return {
            "Action": Action,
            "AwgId": AwgId,
            "AwgSetting": AwgSetting,
            "RunitId": RunitId,
            "RunitSetting": RunitSetting,
            "TriggerSetting": TriggerSetting,
        }[name]
    raise AttributeError(name)
