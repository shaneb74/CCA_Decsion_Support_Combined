# cost_controls.py
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Tuple
import streamlit as st

# ---------------- Location (single control) ----------------

_STATE_FACTORS: Dict[str, float] = {
    "National": 1.00,
    "California": 1.25,
    "Florida": 1.05,
    "Texas": 0.95,
    "Washington": 1.15,
}

def _get_cost_state() -> Tuple[str, float]:
    state = st.session_state.get("cost_state", "National")
    if state not in _STATE_FACTORS:
        state = "National"
    return state, _STATE_FACTORS[state]

def render_location_control() -> None:
    """Exactly one location control. Persists to st.session_state.cost_state."""
    current = st.session_state.get("cost_state", "National")
    choice = st.selectbox(
        "Location",
        list(_STATE_FACTORS.keys()),
        index=list(_STATE_FACTORS.keys()).index(current) if current in _STATE_FACTORS else 0,
        key="__loc_control__",
        help="Used to scale care costs. One selector for the whole plan.",
    )
    if choice != current:
        st.session_state.cost_state = choice  # persist

# ---------------- Small helpers ----------------

def _ns(**kwargs) -> SimpleNamespace:
    ns = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns

def _metric(label: str, dollars: int) -> None:
    st.metric(label, f"${int(dollars):,}")

def _select(label: str, options: list[str], key: str, index: int = 0) -> str:
    if index < 0 or index >= len(options):
        index = 0
    return st.selectbox(label, options, index=index, key=key)

# ---------------- Per-scenario UI blocks ----------------

def _ui_assisted_living(pid: str, name: str) -> Dict[str, Any]:
    # drop-downs (no sliders here)
    care_levels = ["Low", "Moderate", "High"]
    room_types  = ["Studio", "1 Bedroom", "2 Bedroom"]
    mobility    = ["Independent", "Some assistance", "Extensive assistance"]
    conditions  = ["None", "Some", "Multiple/Complex"]

    al_level = _select("Care Level (staffing intensity)", care_levels, key=f"{pid}_al_level", index=1)
    room     = _select("Room Type", room_types, key=f"{pid}_al_room", index=1)
    mobi     = _select("Mobility", mobility, key=f"{pid}_al_mobility", index=0)
    cond     = _select("Chronic Conditions", conditions, key=f"{pid}_al_cond", index=1)

    return {
        "al_care_level": al_level,
        "al_room_type": room,
        "al_mobility": mobi,
        "al_conditions": cond,
    }

def _ui_in_home(pid: str, name: str) -> Dict[str, Any]:
    # sliders only for hours/days; optional conditions as a drop-down
    hours = st.slider("Hours per day — " + name, min_value=1, max_value=24, value=4, step=1, key=f"{pid}_ih_hours")
    days  = st.slider("Days per month — " + name, min_value=1, max_value=31, value=20, step=1, key=f"{pid}_ih_days")
    conditions = _select(
        "Care Conditions — " + name,
        ["None", "Some", "Multiple/Complex"],
        key=f"{pid}_ih_cond",
        index=0,
    )
    return {
        "ih_hours_per_day": hours,
        "ih_days_per_month": days,
        "ih_conditions": conditions,
    }

def _ui_memory_care(pid: str, name: str) -> Dict[str, Any]:
    care_levels = ["Standard", "Enhanced", "Intensive"]
    conditions  = ["None", "Some", "Multiple/Complex"]

    level = _select("Care Level — " + name, care_levels, key=f"{pid}_mc_level", index=0)
    cond  = _select("Chronic Conditions — " + name, conditions, key=f"{pid}_mc_cond", index=1)

    return {
        "mc_care_level": level,
        "mc_conditions": cond,
    }

# ---------------- Render + compute ----------------

def render_costs_for_active_recommendations(*, planner, calculator) -> int:
    """
    Shows the cost controls for each person based on their chosen scenario and
    calls calculator.monthly_cost(...) with a unified inputs object so the engine
    can compute the final number. Returns the combined total.
    """
    people = st.session_state.get("people", [])
    overrides = st.session_state.get("care_overrides", {})
    st.session_state.setdefault("person_costs", {})

    state_name, state_factor = _get_cost_state()
    combined = 0

    for p in people:
        pid = p["id"]
        name = p["display_name"]

        # scenario comes from override if present; else from planner result
        rec_obj = st.session_state.get("planner_results", {}).get(pid)
        rec_type = getattr(rec_obj, "care_type", None) if rec_obj else None
        scen = overrides.get(pid, rec_type or "none")

        st.subheader(f"{name} — Scenario: {scen.replace('_',' ').title()}")

        # Build option set per scenario
        extra: Dict[str, Any] = {}
        if scen == "assisted_living":
            extra = _ui_assisted_living(pid, name)
        elif scen == "in_home":
            extra = _ui_in_home(pid, name)
        elif scen == "memory_care":
            extra = _ui_memory_care(pid, name)
        else:
            extra = {}

        # Compose the unified input object for the calculator
        inputs = _ns(
            person_id=pid,
            name=name,
            state=state_name,
            state_factor=state_factor,
            care_type=scen,
            **extra,
        )

        # Compute (let CalculatorEngine do the math from inputs)
        try:
            monthly = int(calculator.monthly_cost(inputs))
        except Exception:
            # Be resilient: treat "none" as 0, otherwise fall back to a baseline
            monthly = 0 if scen == "none" else 6500

        _metric("Estimated Monthly Cost", monthly)
        st.session_state["person_costs"][pid] = monthly
        combined += monthly

        st.divider()

    return combined
