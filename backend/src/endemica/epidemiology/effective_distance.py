r"""Effective distance over the passenger-flow network.

**Question answered.** Which origins are "close" to a destination in terms of
passenger movement rather than kilometres — including journeys that route
through a hub?

**Model (Brockmann & Helbing, Science 2013).** For a directed network of
passenger flows :math:`F_{mn}`, the fraction of travellers leaving :math:`m`
who go directly to :math:`n` is

.. math::

    P_{mn} = \frac{F_{mn}}{F_m}, \qquad F_m = \sum_j F_{mj}

and the effective length of that edge is

.. math::

    d(m, n) = 1 - \ln P_{mn}

The effective distance between two countries is the **shortest path** over
these edge lengths. Because every :math:`P_{mn} \le 1`, every edge length is
:math:`\ge 1`, so all weights are positive and Dijkstra's algorithm applies.

**Why this shape.** The length adds :math:`-\ln P` (large when the route
carries a small share of the origin's traffic) to a constant 1 per hop, so
taking an extra hop is penalised even when both legs are busy. The result is
that a journey through Istanbul, Dubai, London, Singapore or Atlanta "counts",
which plain geographic distance cannot express.

**Implementation requirements and how they are met.**

* A zero or missing flow produces **no edge** rather than an infinite weight,
  so :math:`\ln 0` is never evaluated.
* Edge direction is preserved: the graph is directed, and
  :math:`d(m,n) \ne d(n,m)` in general.
* A node with no outgoing flow has no outgoing edges and is simply
  unreachable-from; a destination with no incoming path returns ``None``, never
  a large finite number.
* Self-loops are dropped: they carry no information and would distort
  :math:`F_m`.

**What this is and is not.** Effective distance is a *ranking* quantity. The
R² of 0.97 quoted in the research note is from Brockmann and Helbing's
**simulated** pandemic, not from Endemica's data and not a measure of this
implementation's accuracy. Endemica uses effective distance to order origins
and to explain hub paths; it does not convert it into an arrival date.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import networkx as nx

from endemica.core.errors import ModelInputError

FlowKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class EffectiveDistancePath:
    """A shortest effective-distance path from an origin to a destination.

    Attributes:
        origin: Starting node.
        destination: Ending node.
        distance: Total effective distance (dimensionless, >= 1 per hop).
        path: Node sequence including both endpoints.
        hops: Number of edges traversed.
        intermediate_nodes: Hub nodes between the endpoints, in order. Empty
            for a direct route.
    """

    origin: str
    destination: str
    distance: float
    path: tuple[str, ...]
    hops: int

    @property
    def intermediate_nodes(self) -> tuple[str, ...]:
        """Hubs between origin and destination, in travel order."""
        return self.path[1:-1]

    @property
    def is_direct(self) -> bool:
        """Whether the shortest path uses a single edge."""
        return self.hops == 1


def build_effective_distance_graph(flows: Mapping[FlowKey, float]) -> nx.DiGraph:
    r"""Build the directed effective-distance graph from passenger flows.

    Args:
        flows: Mapping of ``(origin, destination)`` to passengers per day.
            Entries that are zero, negative, non-finite, or self-loops are
            excluded; see module docstring for why.

    Returns:
        A :class:`networkx.DiGraph` whose edges carry ``weight`` (the effective
        length :math:`1 - \ln P`), ``share`` (:math:`P_{mn}`) and
        ``passengers_per_day``.

    Raises:
        ModelInputError: If any retained flow is non-finite. A negative or zero
            flow is dropped rather than raising, because a sparse flow matrix
            legitimately contains both; a NaN indicates a build-step bug.

    Example:
        A hub network: A sends most traffic to the hub H, and H feeds B.

        >>> g = build_effective_distance_graph({
        ...     ("A", "H"): 900.0, ("A", "B"): 100.0,
        ...     ("H", "B"): 500.0, ("H", "A"): 500.0,
        ... })
        >>> round(g["A"]["H"]["weight"], 4)
        1.1054
        >>> round(g["A"]["B"]["weight"], 4)
        3.3026
    """
    outflow: dict[str, float] = {}
    retained: list[tuple[str, str, float]] = []

    for (origin, destination), passengers in flows.items():
        if not math.isfinite(passengers):
            msg = f"flow {origin}->{destination} is not finite: {passengers!r}"
            raise ModelInputError(msg)
        # A zero flow means "no observed movement", which is the absence of an
        # edge, not an edge of infinite length. Dropping it keeps log() safe.
        if passengers <= 0.0 or origin == destination:
            continue
        retained.append((origin, destination, passengers))
        outflow[origin] = outflow.get(origin, 0.0) + passengers

    graph = nx.DiGraph()
    graph.add_nodes_from({n for edge in retained for n in edge[:2]})
    for origin, destination, passengers in retained:
        share = passengers / outflow[origin]
        graph.add_edge(
            origin,
            destination,
            weight=1.0 - math.log(share),
            share=share,
            passengers_per_day=passengers,
        )
    return graph


def effective_distance(
    graph: nx.DiGraph, origin: str, destination: str
) -> EffectiveDistancePath | None:
    """Return the shortest effective-distance path, or ``None`` if unreachable.

    Args:
        graph: Graph from :func:`build_effective_distance_graph`.
        origin: Source node.
        destination: Target node.

    Returns:
        An :class:`EffectiveDistancePath`, or ``None`` when either node is
        absent from the graph or no directed path exists. ``None`` is returned
        rather than ``inf`` so the caller reports "not reachable in the flow
        data we hold" instead of a numeric distance.

    Example:
        The hub path (1.1054 + 1.6931 = 2.7985) beats the thin direct route
        (3.3026), which is the behaviour effective distance exists to capture.

        >>> g = build_effective_distance_graph({
        ...     ("A", "H"): 900.0, ("A", "B"): 100.0,
        ...     ("H", "B"): 500.0, ("H", "A"): 500.0,
        ... })
        >>> path = effective_distance(g, "A", "B")
        >>> path.path, round(path.distance, 4)
        (('A', 'H', 'B'), 2.7985)
        >>> path.intermediate_nodes
        ('H',)
        >>> effective_distance(g, "B", "A") is None
        True
    """
    if origin == destination:
        return EffectiveDistancePath(origin, destination, 0.0, (origin,), 0)
    if origin not in graph or destination not in graph:
        return None
    try:
        length, nodes = nx.single_source_dijkstra(
            graph, origin, target=destination, weight="weight"
        )
    except nx.NetworkXNoPath:
        return None
    return EffectiveDistancePath(
        origin=origin,
        destination=destination,
        distance=float(length),
        path=tuple(nodes),
        hops=len(nodes) - 1,
    )


def rank_origins_by_effective_distance(
    graph: nx.DiGraph, destination: str, origins: Iterable[str]
) -> list[EffectiveDistancePath]:
    """Rank candidate origins by effective distance to one destination.

    Computes distances with a single reverse-graph Dijkstra rather than one
    search per origin, so the cost is O(E log V) for the whole ranking.

    Args:
        graph: Graph from :func:`build_effective_distance_graph`.
        destination: The destination to measure towards.
        origins: Candidate origin nodes.

    Returns:
        Paths sorted by ascending distance. Origins with no path to the
        destination are omitted; the caller can detect them by comparing
        against the input.
    """
    if destination not in graph:
        return []

    # Reversing the view costs nothing and lets one Dijkstra answer every
    # origin at once. Path node order is then reversed back to travel order.
    reverse = graph.reverse(copy=False)
    lengths, paths = nx.single_source_dijkstra(reverse, destination, weight="weight")

    results: list[EffectiveDistancePath] = []
    for origin in origins:
        if origin == destination or origin not in lengths:
            continue
        nodes = tuple(reversed(paths[origin]))
        results.append(
            EffectiveDistancePath(
                origin=origin,
                destination=destination,
                distance=float(lengths[origin]),
                path=nodes,
                hops=len(nodes) - 1,
            )
        )
    results.sort(key=lambda p: p.distance)
    return results
