# cost_controls.py — single location control + per-scenario cost panels (fixed)
from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, Any, List
import streamlit as st

# ---- Single source of truth for location factors ----
LOCATION_FACTORS = {
    "National": 1.00,
    "Washington": 1.15,
    "California": 1.25,
    "Texas": 0.95,
    "Florida": 1.05,
}

# Chronic condition options (shared with PFMA)
CONDITION_OPTIONS: List[str] = [
    "Dementia / memory loss",
    "Parkinson's",
    "Stroke history",
    "Diabetes",
    "CHF / heart disease",
    "COPD / breathing issues",
    "Cancer (active)",
    "Depression / anxiety",
    "Other",
]


def _derive_chronic_for_engine(selected: List[str]) -> str:
    """
    Keep engine inputs stable: one of {"None","Diabetes","Parkinson's","Complex"}.
    - None => "None"
    - Single selection that is Diabetes or Parkinson's => pass that exact label
    - Anything else (multiple selections or other conditions) => "Complex"
    """
    if not selected:
        return "None"
    if len(selected) == 1 and selected[0] in {"Diabetes", "Parkinson's"}:
        return selected[0]
    return "Complex"


def render_location_control() -> None:
    """One global location control for the whole Cost Planner step."""
    choices = list(LOCATION_FACTORS.keys())
    current = st.session_state.get("cost_location", "National")
    try:
        idx = choices.index(current)
    except ValueError:
        idx = 0
    choice = st.selectbox("Location", choices, index=idx, key="cost_location_select")
    # Persist normalized fields
    st.session_state.cost_location = choice
    st.session_state.location_factor = float(LOCATION_FACTORS.get(choice, 1.0))


def _init_person_costs():
    if "person_costs" not in st.session_state:
        st.session_state.person_costs = {}


def _get_override(pid: str, default_care: str) -> str:
    co = st.session_state.get("care_overrides", {})
    return co.get(pid, default_care)


def _prefill_from_flags(pid: str) -> Dict[str, Any]:
    """
    Seed defaults based on flags from planner_results (wheelchair, etc.).
    Returns:
      {
        "mobility": "None"|"Walker"|"Wheelchair",
        "chronic_single": "None"|"Diabetes"|"Parkinson's"|"Complex",
      }
    """
    res = st.session_state.get("planner_results", {}).get(pid)
    flags = set(getattr(res, "flags", []) if res else [])

    mobility = (
        "Wheelchair"
        if "high_mobility_dependence" in flags
        else ("Walker" if "moderate_mobility" in flags else "None")
    )

    # Legacy single-value seed; used only to suggest a default selection
    chronic_single = (
        "Complex"
        if "complex_condition" in flags
        else ("Parkinson's" if "parkinsons" in flags else ("Diabetes" if "diabetes" in flags else "None"))
    )
    return {"mobility": mobility, "chronic_single": chronic_single}


def _inputs_namespace(**kwargs) -> SimpleNamespace:
    ns = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


def _panel_assisted_living(pid: str, name: str, lf: float) -> int:
    seeds = _prefill_from_flags(pid)

    c1, c2 = st.columns(2)
    with c1:
        st.selectbox(
            f"{name} • Care level",
            ["Light", "Moderate", "High"],
            key=f"{pid}_al_care_level",
        )
        st.selectbox(
            f"{name} • Room type",
            ["Studio", "1 Bedroom", "2 Bedroom", "Shared"],
            key=f"{pid}_al_room_type",
        )
    with c2:
        st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_al_mobility",
        )

        # New: multiselect chronic conditions (saved for PFMA).
        # IMPORTANT: Do NOT write to this widget key programmatically.
        default_conditions = st.session_state.get(f"al_conditions_{pid}")
        if default_conditions is None and seeds["chronic_single"] in {"Diabetes", "Parkinson's"}:
            default_conditions = [seeds["chronic_single"]]

        al_conditions = st.multiselect(
            f"{name} • Chronic conditions",
            CONDITION_OPTIONS,
            default=default_conditions,
            key=f"al_conditions_{pid}",
        )

    # Derive the single engine-friendly value and store under a DIFFERENT key
    al_chronic_for_engine = _derive_chronic_for_engine(al_conditions)
    st.session_state[f"{pid}_al_chronic"] = al_chronic_for_engine

    # Compute
    from engines import CalculatorEngine

    calc = CalculatorEngine()
    inputs = _inputs_namespace(
        care_type="assisted_living",
        location_factor=lf,
        al_care_level=st.session_state[f"{pid}_al_care_level"],
        al_room_type=st.session_state[f"{pid}_al_room_type"],
        al_mobility=st.session_state[f"{pid}_al_mobility"],
        al_chronic=st.session_state[f"{pid}_al_chronic"],  # single value for engine
    )
    return int(calc.monthly_cost(inputs))


def _panel_in_home(pid: str, name: str, lf: float) -> int:
    seeds = _prefill_from_flags(pid)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        st.slider(
            f"{name} • Hours per day",
            min_value=1,
            max_value=24,
            value=int(st.session_state.get(f"{pid}_ih_hours", 4)),
            key=f"{pid}_ih_hours",
        )
    with c2:
        st.slider(
            f"{name} • Days per month",
            min_value=1,
            max_value=31,
            value=int(st.session_state.get(f"{pid}_ih_days", 20)),
            key=f"{pid}_ih_days",
        )
    with c3:
        st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_ih_mobility",
        )

    # Keep in-home chronic as the original single-select
    st.selectbox(
        f"{name} • Chronic condition",
        ["None", "Diabetes", "Parkinson's", "Complex"],
        index=["None", "Diabetes", "Parkinson's", "Complex"].index(seeds["chronic_single"]),
        key=f"{pid}_ih_chronic",
    )

    from engines import CalculatorEngine

    calc = CalculatorEngine()
    inputs = _inputs_namespace(
        care_type="in_home",
        location_factor=lf,
        ih_hours_per_day=st.session_state[f"{pid}_ih_hours"],
        ih_days_per_month=st.session_state[f"{pid}_ih_days"],
        ih_mobility=st.session_state[f"{pid}_ih_mobility"],
        ih_chronic=st.session_state[f"{pid}_ih_chronic"],
    )
    return int(calc.monthly_cost(inputs))


def _panel_memory_care(pid: str, name: str, lf: float) -> int:
    seeds = _prefill_from_flags(pid)

    c1, c2 = st.columns(2)
    with c1:
        st.selectbox(
            f"{name} • Memory care level",
            ["Standard", "High Acuity"],
            key=f"{pid}_mc_level",
        )
        st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_mc_mobility",
        )
    with c2:
        # New: multiselect chronic conditions (saved for PFMA).
        # IMPORTANT: Do NOT write to this widget key programmatically.
        default_conditions = st.session_state.get(f"mc_conditions_{pid}")
        if default_conditions is None and seeds["chronic_single"] in {"Diabetes", "Parkinson's"}:
            default_conditions = [seeds["chronic_single"]]

        mc_conditions = st.multiselect(
            f"{name} • Chronic conditions",
            CONDITION_OPTIONS,
            default=default_conditions,
            key=f"mc_conditions_{pid}",
        )

    # Derive the single engine-friendly value and store under a DIFFERENT key
    mc_chronic_for_engine = _derive_chronic_for_engine(mc_conditions)
    st.session_state[f"{pid}_mc_chronic"] = mc_chronic_for_engine

    from engines import CalculatorEngine

    calc = CalculatorEngine()
    inputs = _inputs_namespace(
        care_type="memory_care",
        location_factor=lf,
        mc_level=st.session_state[f"{pid}_mc_level"],
        mc_mobility=st.session_state[f"{pid}_mc_mobility"],
        mc_chronic=st.session_state[f"{pid}_mc_chronic"],  # single value for engine
    )
    return int(calc.monthly_cost(inputs))


def render_costs_for_active_recommendations(*, calculator=None, **_ignore) -> int:
    """
    Draw per-person scenario controls and compute monthly costs through CalculatorEngine.
    Returns combined total. Updates st.session_state.person_costs.
    Accepts and ignores extra kwargs like planner= to stay compatible with app.py.
    """
    _init_person_costs()
    lf = float(st.session_state.get("location_factor", 1.0))

    people = st.session_state.get("people", [])
    planner_results = st.session_state.get("planner_results", {})

    combined = 0
    for p in people:
        pid = p["id"]
        name = p["display_name"]
        rec = planner_results.get(pid)
        recommended = getattr(rec, "care_type", "in_home") if rec else "in_home"
        chosen = _get_override(pid, recommended)

        st.subheader(f"{name} — Scenario: {chosen.replace('_', ' ').title()}")

        if chosen == "assisted_living":
            monthly = _panel_assisted_living(pid, name, lf)
        elif chosen == "memory_care":
            monthly = _panel_memory_care(pid, name, lf)
        elif chosen == "in_home":
            monthly = _panel_in_home(pid, name, lf)
        else:
            monthly = 0

        st.metric("Estimated Monthly Cost", f"${monthly:,.0f}")
        st.session_state.person_costs[pid] = int(monthly)
        combined += int(monthly)
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${combined:,.0f}")
    return combined
