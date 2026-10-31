import networkx as nx
import pytest

from warehouse_ai.models.travel import (
    build_warehouse_graph,
    route_length,
    shortest_distance,
    wave_travel,
)


@pytest.fixture
def synthetic_warehouse():
    """Build a tiny synthetic 2-aisle layout with known analytical distances.

    Layout Geometry
    ---------------
    - Depot: (0, 0)
    - Left corridor (LC): x = 0 connecting Aisle 1 (0, 0) and Aisle 2 (0, 10), length = 10
    - Right corridor (RC): x = 20 connecting Aisle 1 (20, 0) and Aisle 2 (20, 10), length = 10
    - Aisle 1 (y = 0):
        (0, 0) <--(5)--> Loc_1A (5, 0) <--(10)--> Loc_1B (15, 0) <--(5)--> (20, 0)
    - Aisle 2 (y = 10):
        (0, 10) <--(5)--> Loc_2A (5, 10) <--(10)--> Loc_2B (15, 10) <--(5)--> (20, 10)
    """
    G = nx.Graph()

    # Support / Corridor nodes
    G.add_node("DEPOT", x=0.0, y=0.0, node_type="support")
    G.add_node("LC_1", x=0.0, y=0.0, node_type="support")
    G.add_node("LC_2", x=0.0, y=10.0, node_type="support")
    G.add_node("RC_1", x=20.0, y=0.0, node_type="support")
    G.add_node("RC_2", x=20.0, y=10.0, node_type="support")

    # Connect corridors along Y
    G.add_edge("LC_1", "LC_2", weight=10.0)
    G.add_edge("RC_1", "RC_2", weight=10.0)
    G.add_edge("DEPOT", "LC_1", weight=0.0)

    # Waypoints along Aisle 1
    G.add_node("WP_1A", x=5.0, y=0.0, node_type="waypoint")
    G.add_node("WP_1B", x=15.0, y=0.0, node_type="waypoint")
    G.add_edge("LC_1", "WP_1A", weight=5.0)
    G.add_edge("WP_1A", "WP_1B", weight=10.0)
    G.add_edge("WP_1B", "RC_1", weight=5.0)

    # Waypoints along Aisle 2
    G.add_node("WP_2A", x=5.0, y=10.0, node_type="waypoint")
    G.add_node("WP_2B", x=15.0, y=10.0, node_type="waypoint")
    G.add_edge("LC_2", "WP_2A", weight=5.0)
    G.add_edge("WP_2A", "WP_2B", weight=10.0)
    G.add_edge("WP_2B", "RC_2", weight=5.0)

    # Shelf locations projected with weight 0
    G.add_node("LOC_1A", x=5.0, y=0.0, z=1, node_type="location")
    G.add_node("LOC_1B", x=15.0, y=0.0, z=2, node_type="location")
    G.add_node("LOC_2A", x=5.0, y=10.0, z=1, node_type="location")
    G.add_node("LOC_2B", x=15.0, y=10.0, z=3, node_type="location")

    G.add_edge("LOC_1A", "WP_1A", weight=0.0)
    G.add_edge("LOC_1B", "WP_1B", weight=0.0)
    G.add_edge("LOC_2A", "WP_2A", weight=0.0)
    G.add_edge("LOC_2B", "WP_2B", weight=0.0)

    return G


def test_synthetic_shortest_distances(synthetic_warehouse):
    G = synthetic_warehouse
    # Distance from depot to Aisle 1 picks
    assert shortest_distance("DEPOT", "LOC_1A", G=G) == 5.0
    assert shortest_distance("DEPOT", "LOC_1B", G=G) == 15.0

    # Distance between picks in the same aisle
    assert shortest_distance("LOC_1A", "LOC_1B", G=G) == 10.0

    # Distance across aisles via Left Corridor: 5 (to LC_1) + 10 (LC_1 to LC_2) + 5 (to LOC_2A) = 20.0
    assert shortest_distance("LOC_1A", "LOC_2A", G=G) == 20.0

    # Distance across aisles via Right Corridor: 5 (to RC_1) + 10 (RC_1 to RC_2) + 5 (to LOC_2B) = 20.0
    assert shortest_distance("LOC_1B", "LOC_2B", G=G) == 20.0


def test_synthetic_route_length(synthetic_warehouse):
    G = synthetic_warehouse
    locs = ["LOC_1A", "LOC_1B", "LOC_2B", "LOC_2A"]

    # Known analytical optimal tour:
    # DEPOT(0,0) -> LOC_1A(5,0) -> LOC_1B(15,0) -> RC_1(20,0) -> RC_2(20,10)
    # -> LOC_2B(15,10) -> LOC_2A(5,10) -> LC_2(0,10) -> DEPOT(0,0)
    # Total distance = 5 + 10 + 5 + 10 + 5 + 10 + 5 + 10 = 60.0
    s_shape_dist = route_length(locs, method="s_shape", depot="DEPOT", G=G)
    assert s_shape_dist == 60.0

    nn_dist = route_length(locs, method="nearest_neighbor", depot="DEPOT", G=G)
    assert nn_dist == 60.0

    lg_dist = route_length(locs, method="largest_gap", depot="DEPOT", G=G)
    assert lg_dist == 60.0


def test_real_warehouse_graph_connectivity():
    G = build_warehouse_graph()
    assert nx.is_connected(G)
    assert G.number_of_nodes() >= 2300

    # Test distance between CC-01 (y=-29) and CC-08 (y=631) along central corridor
    # Distance = 631 - (-29) = 660.0
    dist_cc = shortest_distance("CC-01", "CC-08", G=G)
    assert dist_cc == 660.0


def test_wave_travel():
    # Test wave travel calculation on a real wave
    res = wave_travel(33168, method="s_shape", vertical_penalty_sec=5.0)
    assert res["wave_id"] == 33168
    assert res["travel_dist"] > 0.0
    assert res["n_locations"] > 0
    assert res["n_picks"] > 0
    assert res["vertical_time_penalty_sec"] >= 0.0
