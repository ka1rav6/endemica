"""Effective-distance graph construction and shortest paths.

Tested against small hand-constructed graphs whose distances can be verified
with a calculator, as AGENTS.md section 10.3 requires.
"""

from __future__ import annotations

import math

import networkx as nx
import pytest

from endemica.core.errors import ModelInputError
from endemica.epidemiology.effective_distance import (
    build_effective_distance_graph,
    effective_distance,
    rank_origins_by_effective_distance,
)


class TestGraphConstruction:
    def test_edge_weight_matches_the_formula_by_hand(self) -> None:
        """A sends 900/1000 of its traffic to H, so d = 1 - ln(0.9)."""
        graph = build_effective_distance_graph({("A", "H"): 900.0, ("A", "B"): 100.0})
        assert graph["A"]["H"]["weight"] == pytest.approx(1.0 - math.log(0.9))
        assert graph["A"]["B"]["weight"] == pytest.approx(1.0 - math.log(0.1))
        assert graph["A"]["H"]["share"] == pytest.approx(0.9)

    def test_a_sole_outgoing_edge_has_weight_one(self) -> None:
        """Share = 1 gives 1 - ln(1) = 1, the minimum possible edge length."""
        graph = build_effective_distance_graph({("A", "B"): 42.0})
        assert graph["A"]["B"]["weight"] == pytest.approx(1.0)

    def test_every_edge_weight_is_at_least_one(self) -> None:
        """Since every share <= 1, no edge can be shorter than one hop."""
        graph = build_effective_distance_graph(
            {("A", "B"): 1.0, ("A", "C"): 999.0, ("B", "C"): 5.0, ("C", "A"): 50.0}
        )
        for _, _, data in graph.edges(data=True):
            assert data["weight"] >= 1.0

    def test_zero_flows_produce_no_edge(self) -> None:
        """log(0) must never be evaluated; absence of flow is absence of edge."""
        graph = build_effective_distance_graph({("A", "B"): 0.0, ("A", "C"): 100.0})
        assert not graph.has_edge("A", "B")
        assert graph.has_edge("A", "C")

    def test_negative_flows_are_dropped(self) -> None:
        graph = build_effective_distance_graph({("A", "B"): -5.0, ("A", "C"): 100.0})
        assert not graph.has_edge("A", "B")

    def test_zero_flows_do_not_inflate_the_outflow_denominator(self) -> None:
        """A dropped edge must not change the shares of the retained ones."""
        with_zero = build_effective_distance_graph({("A", "B"): 0.0, ("A", "C"): 100.0})
        without = build_effective_distance_graph({("A", "C"): 100.0})
        assert with_zero["A"]["C"]["weight"] == pytest.approx(without["A"]["C"]["weight"])

    def test_self_loops_are_dropped(self) -> None:
        graph = build_effective_distance_graph({("A", "A"): 500.0, ("A", "B"): 100.0})
        assert not graph.has_edge("A", "A")
        assert graph["A"]["B"]["share"] == pytest.approx(1.0)

    def test_non_finite_flow_is_an_error(self) -> None:
        """NaN indicates a build-step bug, unlike a legitimately absent flow."""
        with pytest.raises(ModelInputError, match="not finite"):
            build_effective_distance_graph({("A", "B"): float("nan")})

    def test_direction_is_preserved(self) -> None:
        graph = build_effective_distance_graph(
            {("A", "B"): 100.0, ("B", "A"): 100.0, ("B", "C"): 300.0}
        )
        # B splits its traffic, A does not, so the two directions differ.
        assert graph["A"]["B"]["weight"] != pytest.approx(graph["B"]["A"]["weight"])

    def test_empty_input_gives_an_empty_graph(self) -> None:
        graph = build_effective_distance_graph({})
        assert graph.number_of_nodes() == 0


class TestShortestPaths:
    @pytest.fixture
    def hub_graph(self) -> nx.DiGraph:
        """A -> H -> B, where the direct A -> B route is thin."""
        return build_effective_distance_graph(
            {
                ("A", "H"): 900.0,
                ("A", "B"): 100.0,
                ("H", "B"): 500.0,
                ("H", "A"): 500.0,
            }
        )

    def test_hub_route_beats_a_thin_direct_route(self, hub_graph: nx.DiGraph) -> None:
        """This is the behaviour effective distance exists to capture."""
        path = effective_distance(hub_graph, "A", "B")
        assert path is not None
        assert path.path == ("A", "H", "B")
        assert path.intermediate_nodes == ("H",)
        assert path.is_direct is False
        expected = (1 - math.log(0.9)) + (1 - math.log(0.5))
        assert path.distance == pytest.approx(expected)
        # Confirm it really is shorter than the single direct hop.
        assert path.distance < 1 - math.log(0.1)

    def test_direct_route_wins_when_it_is_the_dominant_one(self) -> None:
        graph = build_effective_distance_graph(
            {("A", "B"): 900.0, ("A", "H"): 100.0, ("H", "B"): 100.0}
        )
        path = effective_distance(graph, "A", "B")
        assert path is not None
        assert path.is_direct is True
        assert path.path == ("A", "B")

    def test_unreachable_destination_returns_none(self, hub_graph: nx.DiGraph) -> None:
        """B has no outgoing flow, so nothing is reachable from it."""
        assert effective_distance(hub_graph, "B", "A") is None

    def test_absent_nodes_return_none(self, hub_graph: nx.DiGraph) -> None:
        assert effective_distance(hub_graph, "A", "ZZZ") is None
        assert effective_distance(hub_graph, "ZZZ", "A") is None

    def test_distance_to_self_is_zero(self, hub_graph: nx.DiGraph) -> None:
        path = effective_distance(hub_graph, "A", "A")
        assert path is not None
        assert path.distance == 0.0
        assert path.hops == 0

    def test_asymmetry(self) -> None:
        graph = build_effective_distance_graph(
            {("A", "B"): 100.0, ("B", "A"): 100.0, ("B", "C"): 900.0}
        )
        there = effective_distance(graph, "A", "B")
        back = effective_distance(graph, "B", "A")
        assert there is not None and back is not None
        assert there.distance != pytest.approx(back.distance)


class TestRanking:
    def test_ranking_is_ascending_and_matches_individual_searches(self) -> None:
        flows = {
            ("NEAR", "DEST"): 900.0,
            ("NEAR", "OTHER"): 100.0,
            ("FAR", "DEST"): 1.0,
            ("FAR", "OTHER"): 999.0,
            ("VIAHUB", "HUB"): 1000.0,
            ("HUB", "DEST"): 800.0,
            ("HUB", "OTHER"): 200.0,
        }
        graph = build_effective_distance_graph(flows)
        ranked = rank_origins_by_effective_distance(graph, "DEST", ["FAR", "NEAR", "VIAHUB"])
        assert [p.origin for p in ranked] == ["NEAR", "VIAHUB", "FAR"]
        assert [p.distance for p in ranked] == sorted(p.distance for p in ranked)
        # The batched reverse-Dijkstra must agree with per-origin searches.
        for path in ranked:
            single = effective_distance(graph, path.origin, "DEST")
            assert single is not None
            assert path.distance == pytest.approx(single.distance)
            assert path.path == single.path

    def test_via_hub_paths_report_their_intermediate_nodes(self) -> None:
        graph = build_effective_distance_graph({("ORIG", "HUB"): 1000.0, ("HUB", "DEST"): 1000.0})
        ranked = rank_origins_by_effective_distance(graph, "DEST", ["ORIG"])
        assert ranked[0].intermediate_nodes == ("HUB",)

    def test_unreachable_origins_are_omitted(self) -> None:
        graph = build_effective_distance_graph({("A", "DEST"): 100.0, ("ISOLATED", "X"): 10.0})
        ranked = rank_origins_by_effective_distance(graph, "DEST", ["A", "ISOLATED", "MISSING"])
        assert [p.origin for p in ranked] == ["A"]

    def test_destination_not_in_graph_gives_an_empty_ranking(self) -> None:
        graph = build_effective_distance_graph({("A", "B"): 1.0})
        assert rank_origins_by_effective_distance(graph, "ZZZ", ["A"]) == []

    def test_the_destination_itself_is_excluded(self) -> None:
        graph = build_effective_distance_graph({("A", "DEST"): 1.0, ("DEST", "A"): 1.0})
        ranked = rank_origins_by_effective_distance(graph, "DEST", ["A", "DEST"])
        assert [p.origin for p in ranked] == ["A"]
