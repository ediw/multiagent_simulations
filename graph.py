from __future__ import annotations

from typing import Dict

import networkx as nx

from models import EdgeState


class AgentGraph:
    """Thin wrapper around ``nx.DiGraph`` storing :class:`EdgeState` per edge."""

    def __init__(self) -> None:
        self._g = nx.DiGraph()

    # --- topology mutation ---------------------------------------------------

    def add_agent(self, agent_id: str) -> None:
        if agent_id not in self._g:
            self._g.add_node(agent_id)

    def add_edge(
        self,
        src: str,
        dst: str,
        base_transfer_cost: float = 1.0,
        latency: float = 0.5,
        historical_success: float = 0.5,
        bidirectional: bool = True,
    ) -> None:
        self.add_agent(src)
        self.add_agent(dst)
        self._g.add_edge(src, dst, state=EdgeState(base_transfer_cost, latency, historical_success))
        if bidirectional:
            self._g.add_edge(dst, src, state=EdgeState(base_transfer_cost, latency, historical_success))

    # --- queries -------------------------------------------------------------

    def neighbors(self, agent_id: str) -> Dict[str, EdgeState]:
        if agent_id not in self._g:
            return {}
        return {dst: self._g[agent_id][dst]["state"] for dst in self._g.successors(agent_id)}

    def all_edges(self) -> Dict[str, Dict[str, EdgeState]]:
        result: Dict[str, Dict[str, EdgeState]] = {}
        for src, dst, data in self._g.edges(data=True):
            result.setdefault(src, {})[dst] = data["state"]
        return result

    def snapshot_trust(self) -> Dict[str, float]:
        return {
            f"{src}->{dst}": data["state"].historical_success
            for src, dst, data in self._g.edges(data=True)
        }

    def has_edge(self, src: str, dst: str) -> bool:
        return self._g.has_edge(src, dst)

    # --- trust update --------------------------------------------------------

    def update_success(self, src: str, dst: str, rewarded_value: float, lam: float) -> None:
        if self._g.has_edge(src, dst):
            edge = self._g[src][dst]["state"]
            edge.historical_success = (1.0 - lam) * edge.historical_success + lam * rewarded_value

    def decay_trust(self, decay: float) -> None:
        """Decay all edge historical_success toward 0.5 by *decay* factor."""
        for _, _, data in self._g.edges(data=True):
            old = data["state"].historical_success
            data["state"].historical_success = 0.5 + decay * (old - 0.5)

    # --- direct access -------------------------------------------------------

    @property
    def nxgraph(self) -> nx.DiGraph:
        """Expose the underlying networkx DiGraph for advanced queries."""
        return self._g
