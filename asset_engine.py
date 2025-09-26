# cost_controls.py — single location control + per-scenario cost panels
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

# Chronic condition options (shared)
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
    """Engine expects one of {None, Diabetes, Parkinson's, Complex}."""
    if not selected:
        return "None"
    if len(selected) == 1 and selected[0] in {"Diabetes", "Parkinson's"}:
        return selected[0]
    return "Complex"

def render_location_control() -> None:
    choice = st.selectbox(
        "Location",
        list(LOCATION_FACTORS.keys()),
        index=list(LOCATION_FACTORS.keys()).index(
            st.session_state.get("cost_location", "National")
        ) if "cost_location" in st.session_state else 0,
        key="cost_location_select",
    )
    st.session_state.cost_location = choice
    st.session_state.location_factor = float(LOCATION_FACTORS.get(choice, 1.0))

def _init_person_costs():
    if "person_costs" not in st.session_state:
        st.session_state.person_costs = {}

def _get_override(pid: str, default_care: str) -> str:
    return st.session_state.get("care_overrides", {}).get(pid, default_care)

def _inputs_namespace(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)

def _record_conditions(pid: str, conditions: list[str], kind: str):
    """Persist conditions for PFMA to see later."""
    if conditions:
        canon = set(st.session_state.get("conditions_canon", []))
        for c in conditions:
            if c:
                canon.add(c)
        st.session_state["conditions_canon"] = sorted(canon)
    st.session_state[f"{kind}_conditions_{pid}"] = conditions

def _panel_assisted_living(pid: str, name: str, lf: float) -> int:
    c1, c2 = st.columns(2)
    with c1:
        care_level = st.selectbox(f"{name} • Care level", ["Light","Moderate","High"], key=f"{pid}_al_care_level")
        room_type  = st.selectbox(f"{name} • Room type", ["Studio","1 Bedroom","2 Bedroom","Shared"], key=f"{pid}_al_room_type")
    with c2:
        mobility = st.selectbox(f"{name} • Mobility", ["None","Walker","Wheelchair"], key=f"{pid}_al_mobility")
        al_conditions = st.multiselect(
            f"{name} • Chronic conditions",
            CONDITION_OPTIONS,
            default=st.session_state.get(f"al_conditions_{pid}", []),
            key=f"al_conditions_{pid}",
        )
        al_chronic_for_engine = _derive_chronic_for_engine(al_conditions)
        st.session_state[f"{pid}_al_chronic"] = al_chronic_for_engine
        _record_conditions(pid, al_conditions, "al")

    from engines import CalculatorEngine
    calc = CalculatorEngine()
    return int(calc.monthly_cost(_inputs_namespace(
        care_type="assisted_living",
        location_factor=lf,
        al_care_level=care_level,
        al_room_type=room_type,
        al_mobility=mobility,
        al_chronic=st.session_state[f"{pid}_al_chronic"],
    )))

def _panel_in_home(pid: str, name: str, lf: float) -> int:
    c1, c2, c3 = st.columns(3)
    with c1:
        hours = st.slider(f"{name} • Hours per day", 1, 24, 4, key=f"{pid}_ih_hours")
    with c2:
        days  = st.slider(f"{name} • Days per month", 1, 31, 20, key=f"{pid}_ih_days")
    with c3:
        mobility = st.selectbox(f"{name} • Mobility", ["None","Walker","Wheelchair"], key=f"{pid}_ih_mobility")
    chronic = st.selectbox(f"{name} • Chronic condition", ["None","Diabetes","Parkinson's","Complex"], key=f"{pid}_ih_chronic")

    from engines import CalculatorEngine
    calc = CalculatorEngine()
    return int(calc.monthly_cost(_inputs_namespace(
        care_type="in_home",
        location_factor=lf,
        ih_hours_per_day=hours,
        ih_days_per_month=days,
        ih_mobility=mobility,
        ih_chronic=chronic,
    )))

def _panel_memory_care(pid: str, name: str, lf: float) -> int:
    c1, c2 = st.columns(2)
    with c1:
        level    = st.selectbox(f"{name} • Memory care level", ["Standard","High Acuity"], key=f"{pid}_mc_level")
        mobility = st.selectbox(f"{name} • Mobility", ["None","Walker","Wheelchair"], key=f"{pid}_mc_mobility")
    with c2:
        mc_conditions = st.multiselect(
            f"{name} • Chronic conditions",
            CONDITION_OPTIONS,
            default=st.session_state.get(f"mc_conditions_{pid}", []),
            key=f"mc_conditions_{pid}",
        )
        mc_chronic_for_engine = _derive_chronic_for_engine(mc_conditions)
        st.session_state[f"{pid}_mc_chronic"] = mc_chronic_for_engine
        _record_conditions(pid, mc_conditions, "mc")

    from engines import CalculatorEngine
    calc = CalculatorEngine()
    return int(calc.monthly_cost(_inputs_namespace(
        care_type="memory_care",
        location_factor=lf,
        mc_level=level,
        mc_mobility=mobility,
        mc_chronic=st.session_state[f"{pid}_mc_chronic"],
    )))

def render_costs_for_active_recommendations(*, calculator=None, **_ignore) -> int:
    _init_person_costs()
    lf = float(st.session_state.get("location_factor", 1.0))
    people = st.session_state.get("people", [])
    planner_results = st.session_state.get("planner_results", {})

    combined = 0
    for p in people:
        pid, name = p["id"], p["display_name"]
        rec = planner_results.get(pid)
        recommended = getattr(rec, "care_type", "in_home") if rec else "in_home"
        chosen = _get_override(pid, recommended)

        st.subheader(f"{name} — Scenario: {chosen.replace('_',' ').title()}")
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
