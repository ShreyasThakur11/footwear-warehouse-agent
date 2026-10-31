"""Warehouse storage allocation, slotting optimization, and pick wave routing."""

from warehouse_ai.optimization.routing import (
    evaluate_scenarios,
    scenario_summary,
    statistical_comparison,
    tour_len,
    tour_nn_2opt,
    tour_serpentine,
)
from warehouse_ai.optimization.slotting import (
    abc_from_counts,
    assign_pick_locations,
    build_demand_profile,
    design_slotting,
    inventory_with_ids,
    min_move_layout,
)

__all__ = [
    "abc_from_counts",
    "build_demand_profile",
    "inventory_with_ids",
    "assign_pick_locations",
    "design_slotting",
    "min_move_layout",
    "tour_nn_2opt",
    "tour_serpentine",
    "tour_len",
    "evaluate_scenarios",
    "scenario_summary",
    "statistical_comparison",
]

