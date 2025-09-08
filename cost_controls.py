# cost_controls.py — cost controls + compute + display (self-contained)

from __future__ import annotations
from typing import Any, Dict, List
import streamlit as st

# ------- Session keys (single source of truth) -------
_LOC_KEY = "cost_state"              # "National", "CA", etc.
_FACTOR_KEY = "cost_factor"          # float multiplier
_PERSON_COSTS = "person_costs"       # {pid: int}
_OVERRIDES = "care_overrides"        # {pid: scenario}
_RESULTS = "planner_results"         # {pid: PlannerResult}
_PEOPLE = "people"                   # list of {"id","display_name",...}

# Default location choices
_LOCATION_OPTIONS = {
    "National": 1.00,
    "California": 1.25,
    "Washington": 1.15,
    "Florida": 1.05,
    "Texas": 0.95,
}

# ------- Selectoption definitions per scenario -------
AL_CARE_LEVELS = ["Low", "Medium", "High"]
AL_ROOM_TYPES  = ["Studio", "1 Bedroom", "2 Bedroom"]
AL_MOBILITY    = ["Independent", "Walker", "Wheelchair"]
AL_CONDITIONS  = ["None", "Some", "Significant"]

MC_CARE_LEVELS = ["Standard", "Enhanced"]
MC_MOBILITY    = ["Independent", "Walker", "Wheelchair"]
MC_CONDITIONS  = ["Mild", "Moderate", "Advanced"]

# In-Home defaults
IN_HOME_DEFAULT_HOURS = 4
IN_HOME_DEFAULT_DAYS  = 20


# --------- Public UI entry points ---------

def render_location_control() -> None:
    """One global location picker. Writes BOTH the state name and the factor."""
    if _LOC_KEY not in st.session_state:
        st.session_state[_LOC_KEY] = "National"
    if _FACTOR_KEY not in st.session_state:
        st.session_state[_FACTOR_KEY] = _LOCATION_OPTIONS[st.session_state[_LOC_KEY]]

    choice = st.selectbox(
        "Location",
        list(_LOCATION_OPTIONS.keys()),
        index=list(_LOCATION_OPTIONS.keys()).index(st.session_state[_LOC_KEY]),
        help="Applies a regional cost multiplier."
    )
    st.session_state[_LOC_KEY] = choice
    st.session_state[_FACTOR_KEY] = float(_LOCATION_OPTIONS[choice])


def render_costs_for_active_recommendations(calculator=None, *_, **__) -> int:
    """
    Draw a cost card for each person using the currently selected scenario
    (recommendation overridden or not). Computes per-person monthly cost via
    calculator and stores in `st.session_state.person_costs`.
    Returns the combined total.
    """
    # Lazy import if calculator not passed
    if calculator is None:
        try:
            from engines import CalculatorEngine
            calculator = CalculatorEngine()
        except Exception:
            calculator = None

    people = st.session_state.get(_PEOPLE, [])
    results = st.session_state.get(_RESULTS, {})
    overrides = st.session_state.get(_OVERRIDES, {})
    if _PERSON_COSTS not in st.session_state:
        st.session_state[_PERSON_COSTS] = {}

    combined = 0
    factor = float(st.session_state.get(_FACTOR_KEY, 1.0))

    for p in people:
        pid = p["id"]
        name = p["display_name"]
        rec = results.get(pid)
        care_type = None
        if hasattr(rec, "care_type"):
            care_type = rec.care_type
        elif isinstance(rec, dict):
            care_type = rec.get("care_type")

        scenario = overrides.get(pid, care_type or "none")

        st.subheader(f"{name} — Scenario: {scenario.replace('_',' ').title()}")

        monthly = _render_scenario_controls_and_compute(
            pid=pid,
            scenario=scenario,
            factor=factor,
            calculator=calculator,
        )

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state[_PERSON_COSTS][pid] = int(monthly)
        combined += int(monthly)
        st.divider()

    return combined


# --------- Internal: draw controls per scenario + compute ---------

def _render_scenario_controls_and_compute(
    pid: str,
    scenario: str,
    factor: float,
    calculator,
) -> int:
    """Draw controls for scenario, compute monthly cost via calculator."""

    if scenario == "none":
        return 0

    # Build a lightweight "inputs" object
    class Inputs: pass
    inp = Inputs()
    inp.care_type = scenario
    inp.region_factor = factor

    if scenario == "assisted_living":
        inp.al_care_level = st.selectbox(
            "Care Level (staffing intensity)", AL_CARE_LEVELS,
            index=_sticky_index(f"{pid}_al_lvl", AL_CARE_LEVELS, "Medium"),
            key=f"{pid}_al_lvl"
        )
        inp.al_room_type = st.selectbox(
            "Room Type", AL_ROOM_TYPES,
            index=_sticky_index(f"{pid}_al_room", AL_ROOM_TYPES, "1 Bedroom"),
            key=f"{pid}_al_room"
        )
        inp.al_mobility = st.selectbox(
            "Mobility", AL_MOBILITY,
            index=_sticky_index(f"{pid}_al_mob", AL_MOBILITY, "Independent"),
            key=f"{pid}_al_mob"
        )
        inp.al_conditions = st.selectbox(
            "Chronic Conditions", AL_CONDITIONS,
            index=_sticky_index(f"{pid}_al_cond", AL_CONDITIONS, "Some"),
            key=f"{pid}_al_cond"
        )

    elif scenario == "memory_care":
        inp.mc_care_level = st.selectbox(
            "Care Level (staffing intensity)", MC_CARE_LEVELS,
            index=_sticky_index(f"{pid}_mc_lvl", MC_CARE_LEVELS, "Standard"),
            key=f"{pid}_mc_lvl"
        )
        inp.mc_mobility = st.selectbox(
            "Mobility", MC_MOBILITY,
            index=_sticky_index(f"{pid}_mc_mob", MC_MOBILITY, "Walker"),
            key=f"{pid}_mc_mob"
        )
        inp.mc_conditions = st.selectbox(
            "Cognitive/Behavioral Needs", MC_CONDITIONS,
            index=_sticky_index(f"{pid}_mc_cond", MC_CONDITIONS, "Moderate"),
            key=f"{pid}_mc_cond"
        )

    elif scenario == "in_home":
        inp.ih_hours_per_day = st.slider(
            "Hours / Day", min_value=1, max_value=24,
            value=st.session_state.get(f"{pid}_ih_hours", IN_HOME_DEFAULT_HOURS),
            key=f"{pid}_ih_hours"
        )
        inp.ih_days_per_month = st.slider(
            "Days / Month", min_value=1, max_value=31,
            value=st.session_state.get(f"{pid}_ih_days", IN_HOME_DEFAULT_DAYS),
            key=f"{pid}_ih_days"
        )

    try:
        if calculator and hasattr(calculator, "monthly_cost"):
            monthly = int(calculator.monthly_cost(inp))
        else:
            monthly = 0
    except Exception:
        monthly = 0

    return max(0, int(monthly))


def _sticky_index(key: str, options: List[str], fallback: str) -> int:
    """Remember last selection for a person; otherwise use fallback."""
    if key in st.session_state and st.session_state[key] in options:
        return options.index(st.session_state[key])
    if fallback in options:
        return options.index(fallback)
    return 0