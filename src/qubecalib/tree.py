"""Tree utilities used by sequence planning internals."""

from __future__ import annotations

from collections import defaultdict, deque


class Tree(defaultdict[int, list[int]]):
    """Directed tree represented as parent-to-children adjacency map."""

    def __init__(self, root: int | None = None):
        """Create an optional-root tree."""
        super().__init__(list)
        if root is not None:
            self[root]

    @property
    def root(self) -> int:
        """
        Return the root node.

        Returns
        -------
        int
            Root node id.
        """
        for parent in self:
            if not any(parent in children for children in self.values()):
                return parent
        raise ValueError("loop detected")

    def adopt(self, parent: int, child: int) -> None:
        """
        Adopt a child node under parent.

        Parameters
        ----------
        parent : int
            Parent node id.
        child : int
            Child node id.
        """
        if child in self.children:
            raise ValueError("The child object is already adopted to another parent.")
        self[parent].append(child)

    def breadth_first_search(self, start: int | None = None) -> list[int]:
        """
        Return BFS order from the specified start node.

        Parameters
        ----------
        start : int | None, optional
            Start node. If omitted, root is used.

        Returns
        -------
        list[int]
            BFS node order.
        """
        start_node = self.root if start is None else start
        order: list[int] = []
        queue: deque[int] = deque([start_node])
        while queue:
            parent = queue.popleft()
            order.append(parent)
            for child in self[parent]:
                queue.append(child)
        return order

    def bfs(self, start: int | None = None) -> list[int]:
        """
        Alias for `breadth_first_search`.

        Parameters
        ----------
        start : int | None, optional
            Start node.

        Returns
        -------
        list[int]
            BFS node order.
        """
        return self.breadth_first_search(start)

    def parentof(self, child: int) -> int:
        """
        Return parent node of the given child.

        Parameters
        ----------
        child : int
            Child node id.

        Returns
        -------
        int
            Parent node id.
        """
        for parent in self:
            if child in self[parent]:
                return parent
        raise ValueError("this node is root")

    def insert(self, parent: int, child: int) -> None:
        """
        Insert a new parent above an existing child.

        Parameters
        ----------
        parent : int
            New parent node id.
        child : int
            Existing child node id.
        """
        old_parent = self.parentof(child)
        self[old_parent].remove(child)
        self.adopt(parent, child)
        self.adopt(old_parent, parent)

    @property
    def parents(self) -> list[int]:
        """
        Return nodes that currently have children.

        Returns
        -------
        list[int]
            Parent node ids.
        """
        return [node for node in self if self[node]]

    @property
    def children(self) -> list[int]:
        """
        Return all child nodes.

        Returns
        -------
        list[int]
            Child node ids.
        """
        return list({child for children in self.values() for child in children})

    @property
    def all(self) -> list[int]:
        """
        Return all node ids.

        Returns
        -------
        list[int]
            Parent and child ids.
        """
        return list(set(self.parents + self.children))

    def duplicate(self) -> Tree:
        """
        Return a shallow duplicate of this tree.

        Returns
        -------
        Tree
            Copied tree.
        """
        new_tree = Tree()
        for parent in self.parents:
            new_tree[parent] = list(self[parent])
        return new_tree


class CostedTree:
    """Tree wrapper that tracks per-node edge costs."""

    def __init__(self) -> None:
        """Create an empty costed tree."""
        self._tree = Tree()
        self._cost: dict[int, float | None] = {}

    def adopt(self, parent: int, child: int, cost: float) -> None:
        """
        Adopt a child and set its edge cost.

        Parameters
        ----------
        parent : int
            Parent node id.
        child : int
            Child node id.
        cost : float
            Edge cost from parent to child.
        """
        self._tree.adopt(parent, child)
        self._cost[child] = cost

    def evaluate(self, root: int | None = None) -> dict[int, float]:
        """
        Evaluate cumulative costs from root to all reachable nodes.

        Parameters
        ----------
        root : int | None, optional
            Root node. If omitted, inferred root is used.

        Returns
        -------
        dict[int, float]
            Total cost by node.
        """
        root_node = self._tree.root if root is None else root
        total_costs: dict[int, float] = {root_node: 0.0}
        bfs_order = self._tree.breadth_first_search(root_node)
        for node in bfs_order[1:]:
            cost = self._cost[node]
            parent_cost = total_costs[self._tree.parentof(node)]
            if cost is None:
                raise ValueError(f"cost is None, {node}: {self._cost}")
            total_costs[node] = cost + parent_cost
        return total_costs

    def parentof(self, child: int) -> int:
        """
        Return parent node of the given child.

        Parameters
        ----------
        child : int
            Child node id.

        Returns
        -------
        int
            Parent node id.
        """
        return self._tree.parentof(child)

    def breadth_first_search(self, start: int | None = None) -> list[int]:
        """
        Return BFS node order.

        Parameters
        ----------
        start : int | None, optional
            Start node.

        Returns
        -------
        list[int]
            BFS node order.
        """
        return self._tree.breadth_first_search(start)
