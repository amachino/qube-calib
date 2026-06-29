"""Direct driver primitives for single-box execution."""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType
from typing import Any, Final, Literal, NamedTuple, TypeAlias, cast

from quel_ic_config import Quel1Box
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode

from qxdriver_quel1.e7awg.compat import CaptureParam, WaveSequence

from .capture_result import CaptureResult, read_capture_result
from .compat import convert_captureparam, convert_wavesequence
from .e7awghal_classification_patch import patched_classification_register_builder

Quel1PortType: TypeAlias = int | tuple[int, int]
_TriggeredCaptureKey: TypeAlias = Literal["__triggered__"]
CaptureFutureKey: TypeAlias = Quel1PortType | _TriggeredCaptureKey
_TRIGGERED_CAPTURE_KEY: Final[_TriggeredCaptureKey] = "__triggered__"


class AwgId(NamedTuple):
    """AWG identifier within a box."""

    port: Quel1PortType
    channel: int


class AwgSetting(NamedTuple):
    """AWG programming setting."""

    awg: AwgId
    wseq: WaveSequence


class RunitId(NamedTuple):
    """Capture runit identifier within a box."""

    port: Quel1PortType
    runit: int


class RunitSetting(NamedTuple):
    """Capture runit programming setting."""

    runit: RunitId
    cprm: CaptureParam


class TriggerSetting(NamedTuple):
    """Mapping from trigger destination port to AWG source."""

    trigger_awg: AwgId
    triggerd_port: Quel1PortType


class Action:
    """Executable direct action for one box."""

    def __init__(
        self,
        box: Quel1Box,
        wseqs: MappingProxyType[AwgId, WaveSequence],
        cprms: MappingProxyType[RunitId, CaptureParam],
        triggers: MappingProxyType[Quel1PortType, AwgId],
    ) -> None:
        self._box: Final[Quel1Box] = box
        self._wseqs: Final[MappingProxyType[AwgId, WaveSequence]] = wseqs
        self._cprms: Final[MappingProxyType[RunitId, CaptureParam]] = cprms
        self._triggers: Final[MappingProxyType[Quel1PortType, AwgId]] = triggers

    @classmethod
    def build(
        cls,
        *,
        box: Quel1Box,
        settings: list[RunitSetting | AwgSetting | TriggerSetting],
    ) -> Action:
        """
        Build and load an action from settings.

        Parameters
        ----------
        box : Quel1Box
            Box target.
        settings : list[RunitSetting | AwgSetting | TriggerSetting]
            Direct-driver settings.

        Returns
        -------
        Action
            Loaded action object.
        """
        wseqs, cprms, triggers = cls.parse_settings(settings)
        action = cls(box, wseqs, cprms, triggers)
        action._load_to_device()
        return action

    @staticmethod
    def parse_settings(
        settings: list[RunitSetting | AwgSetting | TriggerSetting],
    ) -> tuple[
        MappingProxyType[AwgId, WaveSequence],
        MappingProxyType[RunitId, CaptureParam],
        MappingProxyType[Quel1PortType, AwgId],
    ]:
        """
        Validate and split settings into AWG/Capture/Trigger maps.

        Parameters
        ----------
        settings : list[RunitSetting | AwgSetting | TriggerSetting]
            Direct-driver settings.

        Returns
        -------
        tuple[MappingProxyType[AwgId, WaveSequence], MappingProxyType[RunitId, CaptureParam], MappingProxyType[Quel1PortType, AwgId]]
            Parsed setting maps.
        """
        if not settings:
            raise ValueError("no settings provided")

        wseqs: dict[AwgId, WaveSequence] = {}
        cprms: dict[RunitId, CaptureParam] = {}
        triggers: dict[Quel1PortType, AwgId] = {}
        for setting in settings:
            if isinstance(setting, AwgSetting):
                wseqs[setting.awg] = setting.wseq
            elif isinstance(setting, RunitSetting):
                cprms[setting.runit] = setting.cprm
            elif isinstance(setting, TriggerSetting):
                triggers[setting.triggerd_port] = setting.trigger_awg
            else:
                raise TypeError(f"unsupported setting: {setting}")

        if wseqs and cprms and not triggers:
            raise ValueError("both wseqs and cprms are provided without triggers")

        if triggers:
            cap_ports = {runit.port for runit in cprms}
            for port in triggers:
                if port not in cap_ports:
                    raise ValueError(
                        f"triggerd port {port} is not provided in runit settings"
                    )
            awgs = set(wseqs.keys())
            for port, awg in triggers.items():
                if awg not in awgs:
                    raise ValueError(
                        f"trigger {awg} for triggerd port {port} is not provided"
                    )

        return (
            MappingProxyType(wseqs),
            MappingProxyType(cprms),
            MappingProxyType(triggers),
        )

    def _load_to_device(self) -> None:
        """Convert and apply AWG/capture settings to the target box."""
        for awg, wseq in self._wseqs.items():
            converted = convert_wavesequence(
                wseq,
                name_prefix=f"p{awg.port}_c{awg.channel}",
            )
            for name, iq in converted.wavedata.items():
                self.box.register_wavedata(
                    port=awg.port,
                    channel=awg.channel,
                    name=name,
                    iq=iq,
                    allow_update=True,
                )
            self.box.config_channel(
                port=awg.port,
                channel=awg.channel,
                awg_param=converted.awg_param,
            )
        for runit, cprm in self._cprms.items():
            capture_param = convert_captureparam(cprm)
            with patched_classification_register_builder(
                required=capture_param.classification_enable
            ):
                self.box.config_runit(
                    port=runit.port,
                    runit=runit.runit,
                    capture_param=capture_param,
                )

    def capture_start(
        self,
        *,
        timecounter: int | None = None,
    ) -> dict[CaptureFutureKey, Any]:
        """
        Start capture tasks according to capture/trigger settings.

        For plain capture this starts CAP units immediately. For triggered
        capture on quelware 0.10 and later, this method delegates to
        `start_capture_by_awg_trigger`, which arms the configured capture
        runits and also takes responsibility for starting the trigger-side
        AWG. In other words, the AWG edge that triggers capture is scheduled
        from this method, not from `start_emission()`.

        The optional `timecounter` is mainly used by multi-box execution. A
        value of `None` means "start now", while an integer schedules the
        trigger-side AWG at that shared counter value after capture has been
        armed. This preserves the effective old 0.8/qubecalib ordering where
        triggered boxes were armed first and all emission happened together
        later.

        Parameters
        ----------
        timecounter : int | None, optional
            Absolute hardware time counter for the trigger-side AWG start.
            When omitted, immediate start is requested. When provided, it is
            forwarded to `start_capture_by_awg_trigger(...)` so capture is
            armed now and the AWG starts at the scheduled counter.

        Returns
        -------
        dict[CaptureFutureKey, Any]
            Future map keyed by capture port or a trigger sentinel key.

        Notes
        -----
        In the triggered path this method returns one combined future entry
        that contains both the capture task and the AWG task. Callers should
        not invoke `start_wavegen()` for the same triggered action afterward,
        because the trigger-side AWG has already been started or reserved here.
        """
        channels = set(self._wseqs)
        runits_by_ports: dict[Quel1PortType, list[int]] = defaultdict(list)
        for runit in self._cprms:
            runits_by_ports[runit.port].append(runit.runit)
        for port, trigger in self._triggers.items():
            if trigger not in channels:
                raise ValueError(
                    f"trigger {trigger} for triggerd port {port} is not provided"
                )
            if port not in runits_by_ports:
                raise ValueError(
                    f"triggerd port {port} is not provided in runit settings"
                )

        if not runits_by_ports:
            return {}

        if self._triggers:
            channel_specs = {(awg.port, awg.channel) for awg in self._wseqs}
            runits = {
                (port, runit)
                for port, runits_ in runits_by_ports.items()
                for runit in runits_
            }
            if timecounter is None:
                cap_task, gen_task = self._box.start_capture_by_awg_trigger(
                    runits=runits,
                    channels=channel_specs,
                )
            else:
                cap_task, gen_task = self._box.start_capture_by_awg_trigger(
                    runits=runits,
                    channels=channel_specs,
                    timecounter=timecounter,
                )
            return {_TRIGGERED_CAPTURE_KEY: (cap_task, gen_task)}

        return {
            port: self._box.start_capture_now(
                {(port, runit) for runit in runits},
            )
            for port, runits in runits_by_ports.items()
        }

    def start_emission(self) -> None:
        """Start wave generation when AWG settings exist."""
        awg_specs = {(awg.port, awg.channel) for awg in self._wseqs}
        if awg_specs:
            task = self._box.start_wavegen(awg_specs)
            task.result()

    def capture_stop(
        self,
        futures: dict[CaptureFutureKey, Any],
    ) -> tuple[
        dict[Quel1PortType, CaptureReturnCode],
        dict[tuple[Quel1PortType, int], CaptureResult],
    ]:
        """
        Resolve capture futures and return status/data maps.

        Parameters
        ----------
        futures : dict[CaptureFutureKey, Any]
            Futures returned by `capture_start`.

        Returns
        -------
        tuple[dict[Quel1PortType, CaptureReturnCode], dict[tuple[Quel1PortType, int], CaptureResult]]
            Flattened status and capture data maps.
        """
        status: dict[Quel1PortType, CaptureReturnCode] = {}
        data: dict[tuple[Quel1PortType, int], CaptureResult] = {}

        triggered_futures = futures.get(_TRIGGERED_CAPTURE_KEY)
        if triggered_futures is not None:
            cap_task, gen_task = cast(tuple[Any, Any], triggered_futures)
            gen_task.result()
            readers = cap_task.result()
            for (port, runit), reader in readers.items():
                status[port] = CaptureReturnCode.SUCCESS
                data[(port, runit)] = read_capture_result(
                    reader,
                    self._cprms[RunitId(port=port, runit=runit)],
                )
            return status, data

        for port, future in futures.items():
            if port == _TRIGGERED_CAPTURE_KEY:
                continue
            readers = future.result()
            status[port] = CaptureReturnCode.SUCCESS
            for (_, runit), reader in readers.items():
                data[(port, runit)] = read_capture_result(
                    reader,
                    self._cprms[RunitId(port=port, runit=runit)],
                )
        return status, data

    def action(
        self,
    ) -> tuple[
        dict[Quel1PortType, CaptureReturnCode],
        dict[tuple[Quel1PortType, int], CaptureResult],
    ]:
        """
        Execute one action cycle and return capture results.

        Returns
        -------
        tuple[dict[Quel1PortType, CaptureReturnCode], dict[tuple[Quel1PortType, int], CaptureResult]]
            Flattened status and capture data maps.
        """
        if self._wseqs and self._cprms and self._triggers:
            futures = self.capture_start()
            return self.capture_stop(futures)
        if self._wseqs and not self._cprms and not self._triggers:
            self.start_emission()
            return {}, {}
        if not self._wseqs and self._cprms and not self._triggers:
            futures = self.capture_start()
            return self.capture_stop(futures)
        raise ValueError("unsupported action")

    @property
    def box(self) -> Quel1Box:
        """
        Return the target box.

        Returns
        -------
        Quel1Box
            Box used for this action.
        """
        return self._box

    @property
    def wave_sequences(self) -> MappingProxyType[AwgId, WaveSequence]:
        """
        Return registered AWG wave-sequence settings.

        Returns
        -------
        MappingProxyType[AwgId, WaveSequence]
            Read-only AWG setting map.
        """
        return self._wseqs

    @property
    def capture_params(self) -> MappingProxyType[RunitId, CaptureParam]:
        """
        Return registered capture-parameter settings.

        Returns
        -------
        MappingProxyType[RunitId, CaptureParam]
            Read-only capture setting map.
        """
        return self._cprms

    @property
    def trigger_settings(self) -> MappingProxyType[Quel1PortType, AwgId]:
        """
        Return trigger mappings.

        Returns
        -------
        MappingProxyType[Quel1PortType, AwgId]
            Read-only trigger map.
        """
        return self._triggers
