"""Pulse-sequence DSL, tree model, and sampling helpers for qubecalib."""

# ruff: noqa: SLF001

from __future__ import annotations

import functools
import itertools
import math
import operator
from collections import deque
from collections.abc import MutableSequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from .tree import CostedTree, Tree

DEFAULT_SAMPLING_PERIOD: float = 2.0


@dataclass
class RunningConfig:
    """Represent `RunningConfig`."""

    contexts: Final[MutableSequence] = field(default_factory=deque)


_rc: Final[RunningConfig] = RunningConfig()


class SequenceTree:
    """Represent `SequenceTree`."""

    def __init__(self) -> None:
        """Execute init."""
        self._tree = CostedTree()
        self._active_node = 0
        self._latest_node = 0
        self._nodes_items: dict[int, Item] = {}

    def append(self, item: Item) -> int:
        """Execute append."""
        self._latest_node += 1
        self._tree.adopt(
            self._active_node,
            self._latest_node,
            cost=-1,
        )
        self._nodes_items[self._latest_node] = item
        self._active_node = self._latest_node
        return self._latest_node

    def branch(self, branch: Branch) -> Branch:
        """Execute branch."""
        branched_node = self._active_node
        self.append(branch)
        branch._next_node = self._active_node
        self._active_node = branched_node
        branch_root = self.append(Dummy())
        branch._root_node = branch_root
        return branch

    def place_slots(self) -> None:
        """Execute place slots."""
        branch_items = [
            self._nodes_items[node]
            for node in self.breadth_first_search()[1:]
            if isinstance(self._nodes_items[node], Branch)
        ]
        for branch_item in reversed(branch_items):
            if not isinstance(branch_item, Branch):
                raise TypeError("branch item must be Branch")
            branch_item.place(self)

        for node, item in self._nodes_items.items():
            self._tree._cost[node] = item.duration
        total_costs = self._tree.evaluate()
        for node, slot in self._nodes_items.items():
            end = total_costs[node]
            if end is None:
                raise ValueError("invalid value of total cost")
            duration = slot.duration
            if duration is None:
                raise ValueError(f"invalid duration of slot {slot}")
            slot.begin = end - duration

    def parentof(self, child: int) -> int:
        """Execute parentof."""
        return self._tree.parentof(child)

    def breadth_first_search(self, start: int | None = None) -> MutableSequence[int]:
        """Execute breadth first search."""
        return self._tree.breadth_first_search(start)


class Item:
    """Represent `Item`."""

    def __init__(
        self,
        duration: float | None = None,
        begin: float | None = None,
    ) -> None:
        """Execute init."""
        self._duration = duration
        self.begin: float | None = begin

    @property
    def duration(self) -> float | None:
        """Return duration."""
        return self._duration

    @duration.setter
    def duration(self, duration: float) -> None:
        """Execute duration."""
        self._duration = duration

    @property
    def end(self) -> float:
        """Return end."""
        if self.begin is None or self.duration is None:
            raise ValueError("begin or duration is None")
        return self.begin + self.duration

    def __repr__(self) -> str:
        """Return a debug representation string."""
        return (
            f"{self.__class__.__name__}(duration={self.duration}, begin={self.begin})"
        )


class Padding(Item):
    """Represent `Padding`."""

    def __init__(self, duration: float | None = None) -> None:
        """Execute init."""
        super().__init__(duration)


class Branch(Item):
    """Represent `Branch`."""

    def __init__(self) -> None:
        """Execute init."""
        super().__init__()
        self._duration = None
        self._next_node: int | None = None
        self._root_node: int | None = None

    def place(self, tree: SequenceTree) -> None:
        """Execute place."""
        for _ in tree.breadth_first_search(self._root_node)[1:]:
            tree._tree._cost[_] = tree._nodes_items[_].duration
        max_duration = max(list(tree._tree.evaluate(self._root_node).values()))
        self.duration = max_duration
        if self._next_node is None:
            raise ValueError("_next_node is None")
        tree._tree._cost[self._next_node] = self.duration

    def __repr__(self) -> str:
        """Return a debug representation string."""
        return f"{self.__class__.__name__}(duration={self.duration}, begin={self.begin}, next_node={self._next_node}, root_node={self._root_node})"


class Dummy(Item):
    """Represent `Dummy`."""

    def __init__(self) -> None:
        """Execute init."""
        super().__init__(0)

    @property
    def duration(self) -> float | None:
        """Return duration."""
        return self._duration

    @duration.setter
    def duration(self, duration: float) -> None:
        """Branch object cannot set duration value."""
        raise ValueError("Branch object cannot set duration value")

    def __repr__(self) -> str:
        """Return a debug representation string."""
        return f"{self.__class__.__name__}(begin={self.begin})"


class DequeWithContext(deque):
    """Represent `DequeWithContext`."""

    def __enter__(self) -> DequeWithContext:
        """Enter the context manager."""
        _rc.contexts.append(self)
        return self

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        _rc.contexts.pop()


class Sequence(DequeWithContext):
    """Represent `Sequence`."""

    def __enter__(self) -> Sequence:
        """Enter the context manager."""
        super().__enter__()
        return self

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        super().__exit__(exception_type, exception_value, traceback)
        self._tree = SequenceTree()
        items: MutableSequence[SequenceTree | MutableSequence[Any]] = []
        for item in self:
            if isinstance(item, SequenceTree):
                tree = item
                root = tree._tree._tree.root
                c = tree._tree._tree[root]
                n = tree._nodes_items
                branch = next(iter([n[_] for _ in c if isinstance(n[_], Branch)]))
                if isinstance(branch, SubSequenceBranch):
                    items.append(item)
                    continue
            if not items:
                items.append([])
            if isinstance(items[-1], SequenceTree):
                items.append([])
            if isinstance(items[-1], SequenceTree):
                raise TypeError("invalid intermediate item container")
            items[-1].append(item)
        _items = []
        for item in items:
            if isinstance(item, SequenceTree):
                _items.append(item)
                continue
            tree = SequenceTree()
            tree.branch(SubSequenceBranch())
            SubSequence.create_tree(tree, item)
            _items.append(tree)
        for item in _items:
            _tree = item
            all_nodes = self._tree._tree._tree.all
            if all_nodes:
                offset = max(all_nodes)
            else:
                offset = 0
            root = _tree._tree._tree.root
            for parent, children in _tree._tree._tree.items():
                if parent == root:
                    self._tree._tree._tree[self._tree._active_node] += [
                        _ + offset for _ in children
                    ]
                else:
                    self._tree._tree._tree[parent + offset] = [
                        _ + offset for _ in children
                    ]
                self._tree._latest_node = max(self._tree._tree._tree.all)
                branches = {
                    _tree._nodes_items[_]
                    for _ in children
                    if isinstance(
                        _tree._nodes_items[_],
                        Branch,
                    )
                }
                if not branches:
                    continue
                for branch in branches:
                    if not isinstance(branch, Branch):
                        continue
                    if not isinstance(branch, Branch):
                        continue
                    if branch._root_node is None:
                        raise ValueError("_root_node is None")
                    if branch._next_node is None:
                        raise ValueError("_next_node is None")
                    branch._root_node += offset
                    branch._next_node += offset
                if parent != root:
                    continue
                branches = {
                    _tree._nodes_items[_]
                    for _ in children
                    if isinstance(
                        _tree._nodes_items[_],
                        Branch,
                    )
                }
                if not branches:
                    continue
                branch = next(iter(branches))
                if not isinstance(branch, Branch):
                    continue
                if branch._next_node is None:
                    raise ValueError("_next_node is None")
                self._tree._active_node = branch._next_node
            for node in _tree.breadth_first_search()[1:]:
                self._tree._nodes_items[node + offset] = _tree._nodes_items[node]
                self._tree._tree._cost[node + offset] = -1
        self._validate_nodes_items()  # for debug

    def _get_tree(self) -> Tree:
        if self._tree is None:
            raise ValueError("SequenceTree is not prepared.")
        return self._tree._tree._tree

    def _get_group_items_by_target(
        self,
    ) -> dict[str, dict[int, MutableSequence[Slot]]]:
        nodes_items = self._tree._nodes_items
        subsequences = [
            _
            for _ in self._tree._nodes_items.values()
            if isinstance(_, SubSequenceBranch)
        ]
        nodes_by_sub = {
            sub: self._tree.breadth_first_search(sub._root_node)
            for sub in subsequences
            if sub._next_node is not None
        }
        result: dict[str, dict[int, MutableSequence[Slot]]] = {}
        for node, item in nodes_items.items():
            if not isinstance(item, Slot):
                continue
            for target in item.targets:
                if target not in result:
                    result[target] = {}
                for sub in subsequences:
                    if sub._next_node is None:
                        continue
                    if sub._next_node not in result[target]:
                        result[target][sub._next_node] = []
                    if (
                        isinstance(item, Slot)
                        and target in item.targets
                        and node in nodes_by_sub[sub]
                    ):
                        result[target][sub._next_node].append(item)

        return result

    def get_group_items_by_target(
        self,
    ) -> dict[str, dict[int, MutableSequence[Slot]]]:
        """Return grouped slot items keyed by target and subsequence node."""
        return self._get_group_items_by_target()

    def _validate_nodes_items(self) -> None:
        for node, item in self._tree._nodes_items.items():
            if not isinstance(item, Branch):
                continue
            if node != item._next_node:
                raise ValueError("invalid status of item")

    def _create_gen_sampled_sequence(
        self,
        target_name: str,
        targets_items: dict[str, dict[int, list[Waveform | Modifier]]],
        sampling_period: float = DEFAULT_SAMPLING_PERIOD,
    ) -> GenSampledSequence:
        items: dict[int, MutableSequence[Waveform | Modifier]] = {
            edge: [slot for slot in slots if isinstance(slot, (Waveform, Modifier))]
            for edge, slots in targets_items[target_name].items()
        }
        edges_items = {
            _: __
            for _, __ in self._tree._nodes_items.items()
            if isinstance(__, SubSequenceBranch)
        }
        subseq_edges = [edge for edge, _ in items.items() if _]
        subseqs = [
            edges_items[_]
            for _ in subseq_edges
            if isinstance(edges_items[_], SubSequenceBranch)
        ]
        nodes: list[float] = [0.0]
        for subseq in subseqs:
            if subseq.begin is None or subseq.end is None or subseq.post_blank is None:
                raise ValueError("subsequence begin/end/post_blank must be set")
            nodes.extend([subseq.begin, subseq.end - subseq.post_blank])
        blanks = [
            end - begin for begin, end in zip(nodes[:-1:2], nodes[1::2], strict=False)
        ] + [None]
        sampled_subsequences = [
            GenSampledSubSequence(
                real=np.real(v),
                imag=np.imag(v),
                repeats=repeats,
                post_blank=(
                    round(blank / sampling_period) if blank is not None else None
                ),
            )
            for (v, _, _), repeats, blank in [
                (
                    Sampler(subseq, slots).sample(
                        over_sampling_ratio=1, difference_type="center"
                    ),
                    subseq.repeats,
                    post_blank,
                )
                for subseq, slots, post_blank in zip(
                    [edges_items[_] for _ in subseq_edges],
                    [items[_] for _ in subseq_edges],
                    list(blanks)[1:],
                    strict=False,
                )
            ]
        ]
        if blanks[0] is None:
            raise ValueError("first element of blanks is None")
        return GenSampledSequence(
            target_name=target_name,
            prev_blank=round(blanks[0] / sampling_period),
            post_blank=None,
            repeats=None,
            sampling_period=sampling_period,
            sub_sequences=sampled_subsequences,
        )

    @classmethod
    def _is_cap_target(
        cls,
        sub_seq_edges__items: dict[int, MutableSequence[Item]],
    ) -> bool:
        return all(
            not bool(_) or all(isinstance(__, Capture) for __ in _)
            for _ in sub_seq_edges__items.values()
        )

    @classmethod
    def _is_gen_target(
        cls,
        sub_seq_edges__items: dict[int, MutableSequence[Item]],
    ) -> bool:
        return all(
            not bool(_) or all(isinstance(__, Waveform) for __ in _)
            for _ in sub_seq_edges__items.values()
        )

    def _create_sampled_sequence(
        self,
    ) -> tuple[
        dict[str, GenSampledSequence],
        dict[str, CapSampledSequence],
    ]:
        group_items = self._get_group_items_by_target()
        _ = {
            target_name: {
                num: [item for item in items if isinstance(item, (Waveform, Modifier))]
                for num, items in num_items.items()
            }
            for target_name, num_items in group_items.items()
        }
        __ = {
            target_name: {num: items for num, items in num_items.items() if items}
            for target_name, num_items in _.items()
        }
        targets_items_gen: dict[str, dict[int, list[Waveform | Modifier]]] = {
            target_name: num_items for target_name, num_items in __.items() if num_items
        }
        _ = {
            target_name: {
                num: [item for item in items if isinstance(item, Capture)]
                for num, items in num_items.items()
            }
            for target_name, num_items in group_items.items()
        }
        __ = {
            target_name: {num: items for num, items in num_items.items() if items}
            for target_name, num_items in _.items()
        }
        targets_items_cap: dict[str, dict[int, list[Capture]]] = {
            target_name: num_items for target_name, num_items in __.items() if num_items
        }
        return (
            {
                _: self._create_gen_sampled_sequence(_, targets_items_gen)
                for _ in targets_items_gen
            },
            {
                _: self._create_cap_sampled_sequence(_, targets_items_cap)
                for _ in targets_items_cap
            },
        )

    def _create_cap_sampled_sequence(
        self,
        target_name: str,
        targets_items: dict[str, dict[int, list[Capture]]],
        sampling_period: float = DEFAULT_SAMPLING_PERIOD,
    ) -> CapSampledSequence:
        edges_items: dict[int, Item] = self._tree._nodes_items

        def sort_key(x: int) -> float:
            b = edges_items[x].begin
            if b is None:
                raise ValueError("begin is None")
            return b

        subseq_edges = sorted(
            [edge for edge, _ in targets_items[target_name].items() if _],
            key=sort_key,
        )
        subseqs: dict[int, SubSequenceBranch] = {
            edge: _
            for edge, _ in [[edge, edges_items[edge]] for edge in subseq_edges]
            if isinstance(_, SubSequenceBranch) and isinstance(edge, int)
        }
        _subseqs = dict(
            zip(
                subseq_edges,
                Utils.align_items(
                    [
                        Item(
                            duration=_._total_duration_contents,
                            begin=_.begin,
                        )
                        for _ in [subseqs[edge] for edge in subseq_edges]
                        if isinstance(_, SubSequenceBranch)
                        if _._total_duration_contents is not None
                    ],
                ),
                strict=False,
            )
        )
        _slots = {
            subseq_edge: Utils.align_items(
                sorted(
                    [
                        Item(duration=_.duration, begin=_.begin)
                        for _ in targets_items[target_name][subseq_edge]
                    ],
                    key=lambda x: x.begin if x.begin is not None else -math.inf,
                )
            )
            for subseq_edge in subseq_edges
        }
        _nodes: dict[int, MutableSequence[float] | MutableSequence] = {
            _: functools.reduce(
                operator.iadd,
                [[_subseqs[_].begin]]
                + [[__.begin, __.end] for __ in _slots[_]]
                + [[_subseqs[_].end]],
                [],
            )
            for _ in subseq_edges
        }
        _blanks = {
            _: [
                end - begin
                for begin, end in zip(_nodes[_][:-1:2], _nodes[_][1::2], strict=False)
            ]
            for _ in subseq_edges
        }
        _durations = {
            _: [
                end - begin
                for begin, end in zip(_nodes[_][1:-1:2], _nodes[_][2::2], strict=False)
            ]
            for _ in subseq_edges
        }
        _subseqs_original = dict(
            zip(
                subseq_edges,
                [
                    Item(
                        duration=_._total_duration_contents,
                        begin=_.begin,
                    )
                    for _ in [subseqs[edge] for edge in subseq_edges]
                    if isinstance(_, SubSequenceBranch)
                    if _._total_duration_contents is not None
                ],
                strict=False,
            )
        )
        _slots_original = {
            subseq_edge: sorted(
                [
                    Item(
                        duration=item.duration,
                        begin=item.begin,
                    )
                    for item in targets_items[target_name][subseq_edge]
                ],
                key=lambda x: x.begin if x.begin is not None else -math.inf,
            )
            for subseq_edge in subseq_edges
        }
        _nodes_original: dict[int, MutableSequence[float] | MutableSequence] = {
            _: functools.reduce(
                operator.iadd,
                [[_subseqs_original[_].begin]]
                + [[__.begin, __.end] for __ in _slots_original[_]]
                + [[_subseqs_original[_].end]],
                [],
            )
            for _ in subseq_edges
        }
        _blanks_original = {
            _: [
                end - begin
                for begin, end in zip(
                    _nodes_original[_][:-1:2], _nodes_original[_][1::2], strict=False
                )
            ]
            for _ in subseq_edges
        }
        _durations_original = {
            _: [
                end - begin
                for begin, end in zip(
                    _nodes_original[_][1:-1:2], _nodes_original[_][2::2], strict=False
                )
            ]
            for _ in subseq_edges
        }

        toplevel_prev_blank = 0
        toplevel_post_blank: float | None = None
        return CapSampledSequence(
            target_name,
            prev_blank=round(toplevel_prev_blank / sampling_period),
            post_blank=(
                round(toplevel_post_blank / sampling_period)
                if toplevel_post_blank is not None
                else None
            ),
            original_prev_blank=toplevel_prev_blank,
            original_post_blank=toplevel_post_blank,
            repeats=None,
            sub_sequences=[
                CapSampledSubSequence(
                    capture_slots=[
                        CaptureSlots(
                            duration=round(duration / sampling_period),
                            post_blank=round(blank / sampling_period),
                            original_duration=duration_original,
                            original_post_blank=blank_original,
                        )
                        for blank, blank_original, duration, duration_original in zip(
                            blanks[1:],
                            blanks_original[1:],
                            durations,
                            durations_original,
                            strict=False,
                        )
                    ],
                    prev_blank=round(blanks[0] / sampling_period),
                    post_blank=(
                        round(subseq.post_blank / sampling_period)
                        if subseq.post_blank is not None
                        else None
                    ),
                    original_prev_blank=blanks_original[0],
                    original_post_blank=(
                        subseq.post_blank if subseq.post_blank is not None else None
                    ),
                    repeats=subseq.repeats,
                )
                for edgeid, subseq, blanks, durations, blanks_original, durations_original in [
                    [
                        _,
                        subseqs[_],
                        _blanks[_],
                        _durations[_],
                        _blanks_original[_],
                        _durations_original[_],
                    ]
                    for _ in subseq_edges
                ]
            ],
        )

    def convert_to_sampled_sequence(
        self,
    ) -> tuple[dict[str, GenSampledSequence], dict[str, CapSampledSequence]]:
        """Execute convert to sampled sequence."""
        self._tree.place_slots()
        return self._create_sampled_sequence()


class SubSequenceBranch(Branch):
    """Represent `SubSequenceBranch`."""

    def __init__(
        self,
        fixed_duration: float | None = None,
        repeats: int = 1,
    ) -> None:
        """Execute init."""
        super().__init__()
        self.repeats = repeats
        self._fixed_duration = fixed_duration
        self._total_duration_contents: float | None = None

    @property
    def repeats(self) -> int:
        """Return repeats."""
        return self._repeats

    @repeats.setter
    def repeats(self, repeats: int) -> None:
        """Execute repeats."""
        if not isinstance(repeats, int):
            raise TypeError("repeats must be int")
        self._repeats = repeats

    @property
    def fixed_duration(self) -> float | None:
        """Return fixed duration."""
        return self._fixed_duration

    def __repr__(self) -> str:
        """Return a debug representation string."""
        return f"{self.__class__.__name__}(duration={self.duration}, begin={self.begin}, next_node={self._next_node}, root_node={self._root_node}, post_blank={self.post_blank}, repeats={self.repeats})"

    def place(self, tree: SequenceTree) -> None:
        """Execute place."""
        for _ in tree.breadth_first_search(self._root_node)[1:]:
            tree._tree._cost[_] = tree._nodes_items[_].duration
        max_duration = max(list(tree._tree.evaluate(self._root_node).values()))
        self._total_duration_contents = max_duration
        if self._fixed_duration is None:
            self.duration = max_duration
        else:
            if max_duration <= self._fixed_duration:
                self.duration = self._fixed_duration
            else:
                raise ValueError(
                    f"Fixed duration {self._fixed_duration} is too smaller than total duration {max_duration}."
                )
        if self._next_node is None:
            raise ValueError("_next_node is None")
        tree._tree._cost[self._next_node] = self.duration

    @property
    def post_blank(self) -> float | None:
        """Return post blank."""
        if self.duration is None:
            raise ValueError("duration is None")
        if self._total_duration_contents is None:
            raise ValueError("place slot first")
        return self.duration - self._total_duration_contents


class SubSequence(DequeWithContext):
    """Represent `SubSequence`."""

    def __enter__(self) -> SubSequence:
        """Enter the context manager."""
        super().__enter__()
        return self

    def __init__(self, duration: float | None = None, repeats: int = 1) -> None:
        """Execute init."""
        if not isinstance(repeats, int):
            raise TypeError("repeats must be int")
        self._repeats = repeats
        self._fixed_duration = duration

    @property
    def repeats(self) -> int:
        """Return repeats."""
        return self._repeats

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        super().__exit__(exception_type, exception_value, traceback)
        tree = SequenceTree()
        tree.branch(
            SubSequenceBranch(
                fixed_duration=self._fixed_duration,
                repeats=self.repeats,
            )
        )
        SubSequence.create_tree(tree, self)
        _rc.contexts[-1].append(tree)

    @classmethod
    def create_tree(cls, tree: SequenceTree, items: MutableSequence) -> None:
        """Execute create tree."""
        for item in items:
            if isinstance(item, Item):
                slot = item
                tree.append(slot)
            elif isinstance(item, SequenceTree):
                _tree = item
                all_nodes = tree._tree._tree.all
                if all_nodes:
                    offset = max(all_nodes)
                else:
                    offset = 0
                root = _tree._tree._tree.root
                for parent, children in _tree._tree._tree.items():
                    if parent == root:
                        tree._tree._tree[tree._active_node] += [
                            _ + offset for _ in children
                        ]
                    else:
                        tree._tree._tree[parent + offset] = [
                            _ + offset for _ in children
                        ]
                    tree._latest_node = max(tree._tree._tree.all)
                    branches = {
                        _tree._nodes_items[_]
                        for _ in children
                        if isinstance(
                            _tree._nodes_items[_],
                            Branch,
                        )
                    }
                    if not branches:
                        continue
                    for branch in branches:
                        if not isinstance(branch, Branch):
                            continue
                        if not isinstance(branch, Branch):
                            continue
                        if branch._root_node is None:
                            raise ValueError("_root_node is None")
                        if branch._next_node is None:
                            raise ValueError("_next_node is None")
                        branch._root_node += offset
                        branch._next_node += offset
                    if parent != root:
                        continue
                    branches = {
                        _tree._nodes_items[_]
                        for _ in children
                        if isinstance(
                            _tree._nodes_items[_],
                            Branch,
                        )
                    }
                    if not branches:
                        continue
                    branch = next(iter(branches))
                    if not isinstance(branch, Branch):
                        continue
                    if branch._next_node is None:
                        raise ValueError("_next_node is None")
                    tree._active_node = branch._next_node
                for node in _tree.breadth_first_search()[1:]:
                    tree._nodes_items[node + offset] = _tree._nodes_items[node]
                    tree._tree._cost[node + offset] = -1
        # return tree


class SeriesBranch(Branch):
    """Represent `SeriesBranch`."""

    pass


class Series(DequeWithContext):
    """Represent `Series`."""

    def __enter__(self) -> Series:
        """Enter the context manager."""
        super().__enter__()
        return self

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        super().__exit__(exception_type, exception_value, traceback)
        tree = SequenceTree()
        _rc.contexts[-1].append(tree)
        tree.branch(SeriesBranch())
        for item in self:
            if isinstance(item, Item):
                slot = item
                tree.append(slot)
            elif isinstance(item, SequenceTree):
                _tree = item
                all_nodes = tree._tree._tree.all
                if all_nodes:
                    offset = max(all_nodes)
                else:
                    offset = 0
                root = _tree._tree._tree.root
                for parent, children in _tree._tree._tree.items():
                    if parent == root:
                        tree._tree._tree[tree._active_node] += [
                            _ + offset for _ in children
                        ]
                    else:
                        tree._tree._tree[parent + offset] = [
                            _ + offset for _ in children
                        ]
                    tree._latest_node = max(tree._tree._tree.all)
                    branches = {
                        _tree._nodes_items[_]
                        for _ in children
                        if isinstance(
                            _tree._nodes_items[_],
                            Branch,
                        )
                    }
                    if not branches:
                        continue
                    for branch in branches:
                        if not isinstance(branch, Branch):
                            continue
                        if not isinstance(branch, Branch):
                            continue
                        if branch._root_node is None:
                            raise ValueError("_root_node is None")
                        if branch._next_node is None:
                            raise ValueError("_next_node is None")
                        branch._root_node += offset
                        branch._next_node += offset
                    if parent != root:
                        continue
                    branches = {
                        _tree._nodes_items[_]
                        for _ in children
                        if isinstance(
                            _tree._nodes_items[_],
                            Branch,
                        )
                    }
                    if not branches:
                        continue
                    branch = next(iter(branches))
                    if not isinstance(branch, Branch):
                        continue
                    if branch._next_node is None:
                        raise ValueError("_next_node is None")
                    tree._active_node = branch._next_node
                for node in _tree.breadth_first_search()[1:]:
                    tree._nodes_items[node + offset] = _tree._nodes_items[node]
                    tree._tree._cost[node + offset] = -1


class FlushleftBranch(Branch):
    """Represent `FlushleftBranch`."""

    pass


class Flushleft(DequeWithContext):
    """Represent `Flushleft`."""

    def __enter__(self) -> Flushleft:
        """Enter the context manager."""
        super().__enter__()
        return self

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        super().__exit__(exception_type, exception_value, traceback)
        tree = SequenceTree()
        _rc.contexts[-1].append(tree)
        branch = tree.branch(FlushleftBranch())
        if branch._root_node is None:
            raise ValueError("_root_node is None")
        tree._active_node = branch._root_node
        for item in self:
            if isinstance(item, Item):
                tree.append(item)
                if branch._root_node is None:
                    raise ValueError("_root_node is None")
                tree._active_node = branch._root_node
            elif isinstance(item, SequenceTree):
                _tree = item
                offset = max(tree._tree._tree.all)
                offset = max(tree._tree._tree.all)
                root = _tree._tree._tree.root
                for parent, children in _tree._tree._tree.items():
                    if parent == root:
                        tree._tree._tree[tree._active_node] += [
                            _ + offset for _ in children
                        ]
                        continue
                    tree._tree._tree[parent + offset] = [_ + offset for _ in children]
                for node in _tree.breadth_first_search()[1:]:
                    _item = _tree._nodes_items[node]
                    tree._nodes_items[node + offset] = _item
                    tree._tree._cost[node + offset] = -1
                    if isinstance(_item, Branch):
                        # _item._tree = tree
                        if _item._root_node is None:
                            raise ValueError("_root_node is None")
                        _item._root_node += offset
                        if _item._next_node is None:
                            raise ValueError("_next_node is None")
                        _item._next_node += offset
                tree._latest_node = max(_tree.breadth_first_search()) + offset
                if branch._root_node is None:
                    raise ValueError("_root_node is None")
                tree._active_node = branch._root_node


class FlushrightBranch(Branch):
    """Represent `FlushrightBranch`."""

    def place(self, tree: SequenceTree) -> None:
        """Execute place."""
        super().place(tree)
        max_duration = self._duration
        if max_duration is None:
            raise ValueError("max_duration is None")
        if self._root_node is None:
            raise ValueError("_root_node is None")
        for _ in tree._tree._tree[self._root_node]:
            durations = [
                value for value in tree._tree.evaluate(_).values() if value is not None
            ]
            if not durations:
                raise ValueError("branch duration cannot be determined")
            branch_duration = max(durations)
            tree._nodes_items[_].duration = max_duration - branch_duration
            tree._tree._cost[_] = tree._nodes_items[_].duration


class Flushright(DequeWithContext):
    """Represent `Flushright`."""

    def __enter__(self) -> Flushright:
        """Enter the context manager."""
        super().__enter__()
        return self

    def __exit__(
        self,
        exception_type: Any,
        exception_value: Any,
        traceback: Any,
    ) -> None:
        """Exit the context manager."""
        super().__exit__(exception_type, exception_value, traceback)
        tree = SequenceTree()
        _rc.contexts[-1].append(tree)
        branch = tree.branch(FlushrightBranch())
        for item in self:
            if isinstance(item, Item):
                tree.append(Padding(0))
                tree.append(item)
                if branch._root_node is None:
                    raise ValueError("_root_node is None")
                tree._active_node = branch._root_node
            elif isinstance(item, SequenceTree):
                tree.append(Padding(0))
                _tree = item
                offset = max(tree._tree._tree.all)
                offset = max(tree._tree._tree.all)
                root = _tree._tree._tree.root
                for parent, children in _tree._tree._tree.items():
                    if parent == root:
                        tree._tree._tree[tree._active_node] += [
                            _ + offset for _ in children
                        ]
                        continue
                    tree._tree._tree[parent + offset] = [_ + offset for _ in children]
                for node in _tree.breadth_first_search()[1:]:
                    _item = _tree._nodes_items[node]
                    tree._nodes_items[node + offset] = _item
                    tree._tree._cost[node + offset] = -1
                    if isinstance(_item, Branch):
                        # _item._tree = tree
                        if _item._root_node is None:
                            raise ValueError("_root_node is None")
                        _item._root_node += offset
                        if _item._next_node is None:
                            raise ValueError("_next_node is None")
                        _item._next_node += offset
                tree._latest_node = max(_tree.breadth_first_search()) + offset
                if branch._root_node is None:
                    raise ValueError("_root_node is None")
                tree._active_node = branch._root_node


class Utils:
    """Represent `Utils`."""

    @classmethod
    def align_items(
        cls,
        items: MutableSequence[Item],
        sampling_period: float = DEFAULT_SAMPLING_PERIOD,
    ) -> MutableSequence[Item]:
        """Execute align items."""
        dt = sampling_period
        aligned_items: list[Item] = []
        for item in items:
            if item.begin is None or item.end is None:
                raise ValueError("begin or end is None")
            aligned_items.append(
                Item(
                    duration=floor(item.end, dt) - floor(item.begin, dt),
                    begin=floor(item.begin, dt),
                )
            )
        return aligned_items

    @classmethod
    def _create_duration_and_blanks(
        cls,
        ranges: MutableSequence[Waveform],
        frame: SubSequenceBranch,
    ) -> tuple[MutableSequence[float], MutableSequence[float | None]]:
        if [x.begin is None for x in ranges]:
            raise ValueError("begin is None")
        slots = sorted(ranges, key=lambda x: x.begin if x.begin is not None else 0)
        _slots = Utils.align_items([_ for _ in slots if isinstance(_, Item)])
        _durations = [_.duration for _ in _slots if isinstance(_.duration, float)]
        _blanks = [
            (
                post.begin - prev.end
                if post.begin is not None and prev.end is not None
                else None
            )
            for prev, post in itertools.pairwise(_slots)
        ] + [
            (
                frame.end - _slots[-1].end
                if frame.end is not None and _slots[-1].end is not None
                else None
            )
        ]
        return _durations, _blanks


def ceil(value: float, unit: float = 1) -> float:
    """
    Round a value up to the nearest multiple of `unit`.

    Parameters
    ----------
    value : float
        Value to round.
    unit : float, default=1
        Quantization step.

    Returns
    -------
    float
        Rounded value.
    """
    exponent = math.floor(math.log10(unit))
    mantissa = unit * 10 ** (-exponent)
    retval = None
    if exponent < 0:
        retval = (
            math.ceil(value * 10 ** (-exponent) / mantissa) * mantissa * 10**exponent
        )
    else:
        retval = (
            math.ceil(value / 10 ** (exponent) / mantissa) * mantissa * 10**exponent
        )
    if (retval - unit) - value < 1e-16:
        return retval - unit
    else:
        return retval


def floor(value: float, unit: float = 1) -> float:
    """
    Round a value down to the nearest multiple of `unit`.

    Parameters
    ----------
    value : float
        Value to round.
    unit : float, default=1
        Quantization step.

    Returns
    -------
    float
        Rounded value.
    """
    exponent = math.floor(math.log10(unit))
    mantissa = unit * 10 ** (-exponent)
    retval = None
    if exponent < 0:
        retval = (
            math.floor(value * 10 ** (-exponent) / mantissa) * mantissa * 10**exponent
        )
    else:
        retval = (
            math.floor(value / 10 ** (exponent) / mantissa) * mantissa * 10**exponent
        )
    if (retval + unit) - value < 1e-16:
        return retval + unit
    else:
        return retval


def padding(duration: float) -> None:
    """
    Add padding with the specified duration to the sequence.

    Parameters
    ----------
    duration : float
        Duration of the padding in ns.
    """
    if len(_rc.contexts):
        Blank(duration=duration).target()


class Slot(Item):
    """
    Slot class for the sequence.

    Parameters
    ----------
    duration : float, optional
        Duration of the slot in ns. Default is None.

    Attributes
    ----------
    duration : float
        Duration of the slot in ns.
    begin : float
        Begin time of the slot in ns.
    end : float
        End time of the slot in ns.
    targets : tuple[str]
        Target qubits.
    """

    def __init__(self, duration: float | None = None) -> None:
        """Execute init."""
        super().__init__(duration)

    def target(self, *targets: str) -> None:
        """Set the target qubits of the slot."""
        self.targets = targets

        # Add the slot to the context
        if len(_rc.contexts):
            _rc.contexts[-1].append(deepcopy(self))


class Blank(Slot):
    """Represent `Blank`."""

    pass


class Capture(Slot):
    """Represent `Capture`."""

    pass


class Modifier(Slot):
    """Apply a complex-valued modifier on top of sampled waveforms."""

    def __init__(self) -> None:
        """Execute init."""
        super().__init__(duration=0)
        self.cmag = 1 + 0j

    def __repr__(self) -> str:
        """Return a debug representation string."""
        return f"{self.__class__.__name__}(begin={self.begin})"

    @property
    def duration(self) -> float | None:
        """Return duration."""
        return self._duration

    @duration.setter
    def duration(self, duration: float) -> None:
        """Branch object cannot set duration value."""
        raise ValueError("Branch object cannot set duration value")

    def func(self, t: float) -> complex:
        """Return the local-time modifier value."""
        return 1 + 0j

    def _func(self, t: float) -> complex:
        """Return the global-time modifier value."""
        if self.begin is None or self.duration is None:
            raise ValueError(
                "Either or both 'begin' and 'duration' are not initialized."
            )
        if self.begin <= t:
            return self.cmag * self.func(t)
        else:
            return 1 + 0j
        # return self.cmag * self.func(t)

    def ufunc(self, t: NDArray) -> NDArray:
        """Execute ufunc."""
        return np.frompyfunc(self._func, 1, 1)(t).astype(complex)


class VirtualZ(Modifier):
    """
    Modify the phase of the waveform.

    Parameters
    ----------
    theta : float, optional
        Phase angle in radian. Default is 0.0. Theta is defined as the rotation angle around the z-axis following the right-handed rule.
    """

    def __init__(self, theta: float = 0.0):
        """Execute init."""
        super().__init__()
        self.cmag = np.exp(-1j * theta)


class Magnifier(Modifier):
    """
    Modify the magnitude of the waveform.

    Parameters
    ----------
    magnitude : float, optional
        Magnitude of the waveform. Default is 1.0.
    """

    def __init__(self, magnitude: float = 1.0):
        """Execute init."""
        super().__init__()
        self.cmag = magnitude * (1 + 0j)


class Frequency(Modifier):
    """
    Modify the frequency of the waveform.

    Parameters
    ----------
    modulation_frequency : float, optional
        Modulation frequency in GHz. Default is 0.0.
    """

    def __init__(self, modulation_frequency: float = 0.0):
        """Execute init."""
        super().__init__()
        self.modulation_frequency = modulation_frequency

    def func(self, t: float) -> complex:
        """Execute func."""
        return np.exp(2j * np.pi * self.modulation_frequency * t)


class Waveform(Slot):
    """
    Waveform class for the sequence.

    Parameters
    ----------
    duration : float, optional
        Duration of the waveform in ns. Default is None.

    Attributes
    ----------
    duration : float
        Duration of the waveform in ns.
    begin : float
        Begin time of the waveform in ns.
    end : float
        End time of the waveform in ns.
    targets : tuple[str]
        Target qubits.
    cmag : complex
        Complex magnitude of the waveform.
    """

    def __init__(
        self,
        duration: float | None = None,
    ) -> None:
        """Execute init."""
        super().__init__(duration=duration)
        self._iq: NDArray | None = None
        self.cmag = 1 + 0j

    def func(self, t: float) -> complex:
        """Return normalized local-time IQ samples for subclasses."""
        raise NotImplementedError()

    def _func(self, t: float) -> complex:
        """Return global-time IQ samples with complex-amplitude scaling."""
        if self.begin is None or self.duration is None:
            raise ValueError(
                "Either or both 'begin' and 'duration' are not initialized."
            )
        if t < self.begin or self.begin + self.duration < t:
            return 0 + 0j
        return self.cmag * self.func(t - self.begin)

    def ufunc(self, t: NDArray) -> NDArray:
        """Execute ufunc."""
        return np.frompyfunc(self._func, 1, 1)(t).astype(complex)

    def scaled(self, scale: float) -> Waveform:
        """Return a copy of the waveform scaled by the given factor."""
        new_waveform = deepcopy(self)
        new_waveform.cmag *= scale
        return new_waveform

    def shifted(self, phase: float) -> Waveform:
        """Return a copy of the waveform shifted by the given phase."""
        new_waveform = deepcopy(self)
        new_waveform.cmag *= np.exp(1j * phase)
        return new_waveform


class RaisedCosFlatTop(Waveform):
    """Represent `RaisedCosFlatTop`."""

    def __init__(
        self,
        duration: float | None = None,
        amplitude: float = 1.0,
        rise_time: float = 0.0,
    ):
        """Execute init."""
        super().__init__(duration=duration)
        self.amplitude = amplitude
        self.rise_time = rise_time

    def func(self, t: float) -> complex:
        """Execute func."""
        if self.duration is None:
            raise ValueError("duration is None")

        flattop_duration = self.duration - self.rise_time * 2

        if flattop_duration < 0:
            raise ValueError("duration is too short for rise_time")

        t1 = 0
        t2 = t1 + self.rise_time
        t3 = t2 + flattop_duration
        t4 = t3 + self.rise_time

        if (t1 <= t) & (t < t2):
            return (
                self.amplitude * (1.0 - np.cos(np.pi * (t - t1) / self.rise_time)) / 2.0
            )
        if (t2 <= t) & (t < t3):
            return self.amplitude
        if (t3 <= t) & (t < t4):
            return (
                self.amplitude * (1.0 - np.cos(np.pi * (t4 - t) / self.rise_time)) / 2.0
            )
        return 0.0 + 0.0j


class Rectangle(Waveform):
    """Represent `Rectangle`."""

    def __init__(
        self,
        duration: float | None = None,
        amplitude: float = 1.0,
    ):
        """Execute init."""
        super().__init__(duration)
        self.amplitude = amplitude

    def func(self, t: float) -> complex:
        """Execute func."""
        if self.duration is None:
            raise ValueError("duration is None")

        if t >= 0 and t < self.duration:
            return complex(self.amplitude)
        return 0 + 0j


class Arbit(Waveform):
    """
    Arbit class for the sequence.

    Parameters
    ----------
    iq : list | NDArray
        IQ data of the waveform.
    """

    def __init__(self, iq: list | NDArray):
        """Execute init."""
        duration = len(iq) * DEFAULT_SAMPLING_PERIOD
        super().__init__(duration)
        self._iq = np.array(iq).astype(complex)

    def func(self, t: float) -> complex:
        """Return `iq(t)` sampled from the internal IQ array."""
        if self._iq is None:
            raise ValueError("_iq is None")
        if self.begin is None or self.duration is None:
            raise ValueError("begin or duration is None")

        D, dt = self.duration, DEFAULT_SAMPLING_PERIOD
        if 0 <= t < D:
            idx = math.floor(t / dt)
            return self._iq[idx]
        else:
            return 0 + 0j

    @property
    def iq(self) -> NDArray:
        """Return the backing IQ array reference."""
        if self.duration is None:
            raise ValueError("duration is None")
        T, dt = self.duration, DEFAULT_SAMPLING_PERIOD
        # N = round(T // dt)
        N = math.ceil(T / dt)
        if self._iq is None or self._iq.shape[0] != N:
            self._iq = np.zeros(N).astype(complex)  # iq data

        return self._iq


class Sampler:
    """Represent `Sampler`."""

    @classmethod
    def create_sampling_timing(
        cls,
        begin: float,
        duration: float,
        over_sampling_ratio: int = 1,
        difference_type: str = "back",
        endpoint: bool = False,
        sampling_period: float = DEFAULT_SAMPLING_PERIOD,
    ) -> NDArray[np.float64]:
        """Create the sample-time axis with optional oversampling."""
        dt = 1 * sampling_period / over_sampling_ratio
        if endpoint:
            duration += dt
        v = np.arange(
            math.ceil(begin / dt) * dt, math.ceil((begin + duration + dt) / dt) * dt, dt
        )
        if difference_type == "back":
            return v[:-1]
        elif difference_type == "center":
            return 0.5 * (v[1:] + v[:-1])
        else:
            raise ValueError(f"difference_type={difference_type} is not supported")

    @classmethod
    def _sample(
        cls,
        sampling_timing: NDArray[np.float64],
        slots: MutableSequence[Waveform | Modifier],
    ) -> NDArray[np.complex128]:
        """Sample slots at the specified sampling times."""
        tstart = sampling_timing[0]
        DT = sampling_timing[1] - sampling_timing[0]
        np_waveform = np.zeros(sampling_timing.size).astype(complex)
        waveforms = [o for o in slots if isinstance(o, Waveform)]
        for w in waveforms:
            if w.begin is None or w.duration is None:
                raise ValueError(f"begin or duration of {w.__class__.__name__} is None")
            B, E = math.ceil((w.begin - tstart) / DT), math.ceil((w.end - tstart) / DT)
            v = w.ufunc(sampling_timing[B:E])
            np_waveform[B:E] += v
        np_modifier = np.ones(sampling_timing.size).astype(complex)
        modifiers = [o for o in slots if isinstance(o, Modifier)]
        for m in modifiers:
            if m.begin is None:
                raise ValueError(f"begin of {m.__class__.__name__} is None")
            B = math.ceil((m.begin - tstart) / DT)
            np_modifier[B:] *= m.ufunc(sampling_timing[B:])
        return np.asarray(np_waveform * np_modifier, dtype=np.complex128)

    def __init__(
        self,
        branch: SubSequenceBranch,
        waveforms: MutableSequence[Waveform | Modifier],
    ) -> None:
        """Execute init."""
        if not isinstance(branch, SubSequenceBranch):
            raise TypeError("branch should be SubSequenceBranch")
        self._branch = branch
        self._waveforms = waveforms

    def sample(
        self,
        over_sampling_ratio: int = 1,
        difference_type: str = "back",
        sampling_period: float = DEFAULT_SAMPLING_PERIOD,
    ) -> tuple[
        NDArray[np.complex128],
        NDArray[np.float64],
        NDArray[np.float64] | None,
    ]:
        """Execute sample."""
        begin = self._branch.begin
        duration = self._branch._total_duration_contents
        if begin is None or duration is None:
            raise ValueError("begin or duration of branch is None")
        if difference_type == "center":
            ts = self.create_sampling_timing(
                begin,
                duration,
                over_sampling_ratio=over_sampling_ratio,
                difference_type="center",
                endpoint=False,
                sampling_period=sampling_period,
            )
            t = self.create_sampling_timing(
                begin,
                duration,
                over_sampling_ratio=over_sampling_ratio,
                difference_type="back",
                endpoint=True,
                sampling_period=sampling_period,
            )
            return self._sample(ts, self._waveforms), t, ts
        else:
            ts = self.create_sampling_timing(
                begin,
                duration,
                over_sampling_ratio=over_sampling_ratio,
                difference_type=difference_type,
                endpoint=False,
                sampling_period=sampling_period,
            )
            return self._sample(ts, self._waveforms), ts, None


@dataclass
class SampledSequenceBase:
    """Represent `SampledSequenceBase`."""

    target_name: str
    prev_blank: int = 0  # words
    sampling_period: float = DEFAULT_SAMPLING_PERIOD
    post_blank: int | None = None  # words
    repeats: int | None = None
    original_prev_blank: float | None = None  # ns
    original_post_blank: float | None = None  # ns
    padding: int = 0  # Sa
    modulation_frequency: float | None = None  # GHz

    def asdict(self) -> dict:
        """Execute asdict."""
        return asdict(self)


@dataclass
class GenSampledSequence(SampledSequenceBase):
    """Represent `GenSampledSequence`."""

    sub_sequences: MutableSequence[GenSampledSubSequence] = field(default_factory=list)
    readout_timings: MutableSequence[list[tuple[float, float]]] | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return super().asdict() | {
            "sub_sequences": [_.asdict() for _ in self.sub_sequences],
            "readout_timings": None,
            "class": self.__class__.__name__,
        }


@dataclass
class GenSampledSubSequence:
    """Represent `GenSampledSubSequence`."""

    real: NDArray[np.float64]
    imag: NDArray[np.float64]
    repeats: int
    post_blank: int | None = None  # samples
    original_post_blank: float | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return {
            "real": self.real.tolist(),
            "imag": self.imag.tolist(),
            "repeats": self.repeats,
            "post_blank": self.post_blank,
            "original_post_blank": self.original_post_blank,
        }


@dataclass
class CapSampledSequence(SampledSequenceBase):
    """Represent `CapSampledSequence`."""

    sub_sequences: MutableSequence[CapSampledSubSequence] = field(default_factory=list)
    readin_offsets: MutableSequence[list[tuple[float, float]]] | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return super().asdict() | {
            "sub_sequences": [_.asdict() for _ in self.sub_sequences],
            "readin_offsets": None,
            "class": self.__class__.__name__,
        }


@dataclass
class CapSampledSubSequence:
    """Represent `CapSampledSubSequence`."""

    capture_slots: MutableSequence[CaptureSlots]
    # duration: int  # samples
    prev_blank: int  # samples
    post_blank: int | None  # samples
    original_prev_blank: float  # ns
    original_post_blank: float | None  # ns
    repeats: int | None

    def asdict(self) -> dict:
        """Execute asdict."""
        return asdict(self)


@dataclass
class CaptureSlots:
    """Represent `CaptureSlots`."""

    duration: int  # samples
    post_blank: int | None  # samples
    original_duration: float  # ns
    original_post_blank: float | None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return {}
