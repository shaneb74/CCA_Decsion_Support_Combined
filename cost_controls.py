# cost_controls.py — single location control + per-scenario cost panels (safe session writes)
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
    choice = st.selectbox(
        "Location",
        list(LOCATION_FACTORS.keys()),
        index=list(LOCATION_FACTORS.keys()).index(
            st.session_state.get("cost_location", "National")
        ) if "cost_location" in st.session_state else 0,
        key="cost_location_select",
    )
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
    """Seed defaults based on flags from planner_results (wheelchair, etc.)."""
    res = st.session_state.get("planner_results", {}).get(pid)
    flags = set(getattr(res, "flags", []) if res else [])
    mobility = (
        "Wheelchair"
        if ("high_mobility_dependence" in flags)
        else ("Walker" if "moderate_mobility" in flags else "None")
    )
    # Legacy single-value seed; used only to suggest a default selection for multiselect
    chronic_single = (
        "Complex"
        if ("complex_condition" in flags)
        else ("Parkinson's" if "parkinsons" in flags else ("Diabetes" if "diabetes" in flags else "None"))
    )
    return {"mobility": mobility, "chronic_single": chronic_single}

def _inputs_namespace(**kwargs) -> SimpleNamespace:
    ns = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns

def _union_into_canon(selected: List[str]) -> None:
    """Update a canonical union of conditions across panels, without touching widget keys."""
    try:
        current = list(st.session_state.get("canon_conditions", []))
    except Exception:
        current = []
    # sanitize to known options
    valid = set(CONDITION_OPTIONS)
    for item in selected or []:
        if item in valid and item not in current:
            current.append(item)
    st.session_state["canon_conditions"] = current

def _record_personal_copy(pid: str, selected: List[str], kind: str) -> None:
    """
    Store the per-person list without mutating the widget key directly.
    We avoid writing to the widget's key (e.g., 'al_conditions_{pid}') to comply with Streamlit rules.
    """
    store_key = f"{kind}_conditions_saved_{pid}"  # e.g., al_conditions_saved_A
    st.session_state[store_key] = list(selected) if selected else []

def format_condition_label(condition: str) -> str:
    """Shorten labels for multiselect chips to prevent overflow."""
    if " / " in condition:
        return condition.split(" / ")[0]  # e.g., "Dementia / memory loss" -> "Dementia"
    return condition[:15] + "..." if len(condition) > 15 else condition

# CSS to improve multiselect chip rendering
st.markdown("""
    <style>
    .stMultiSelect [role="option"] {
        padding: 5px 10px;
        margin: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .stMultiSelect div[role="listbox"] {
        max-height: 200px;
        overflow-y: auto;
    }
    </style>
""", unsafe_allow_html=True)

def _panel_assisted_living(pid: str, name: str, lf: float) -> int:
    seeds = _prefill_from_flags(pid)
    c1, c2 = st.columns([1, 1.5])  # Widen multiselect column
    with c1:
        care_level = st.selectbox(
            f"{name} • Care level",
            ["Light", "Moderate", "High"],
            key=f"{pid}_al_care_level",
        )
        room_type = st.selectbox(
            f"{name} • Room type",
            ["Studio", "1 Bedroom", "2 Bedroom", "Shared"],
            key=f"{pid}_al_room_type",
        )
    with c2:
        mobility = st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_al_mobility",
        )
        default_conditions = st.session_state.get(f"al_conditions_saved_{pid}", [])
        if default_conditions is None:
            default_conditions = [seeds["chronic_single"]] if seeds["chronic_single"] in {"Diabetes", "Parkinson's"} else []
        al_conditions = st.multiselect(
            f"{name} • Chronic conditions",
            CONDITION_OPTIONS,
            default=default_conditions,
            format_func=format_condition_label,
            key=f"al_conditions_{pid}",
            max_selections=5,
        )
        al_chronic_for_engine = _derive_chronic_for_engine(al_conditions)
        st.session_state[f"{pid}_al_chronic"] = al_chronic_for_engine
        _record_personal_copy(pid, al_conditions, "al")
        _union_into_canon(al_conditions)
    from engines import CalculatorEngine
    calc = CalculatorEngine()
    inputs = _inputs_namespace(
        care_type="assisted_living",
        location_factor=lf,
        al_care_level=st.session_state[f"{pid}_al_care_level"],
        al_room_type=st.session_state[f"{pid}_al_room_type"],
        al_mobility=st.session_state[f"{pid}_al_mobility"],
        al_chronic=st.session_state[f"{pid}_al_chronic"],
    )
    return int(calc.monthly_cost(inputs))

def _panel_in_home(pid: str, name: str, lf: float) -> int:
    seeds = _prefill_from_flags(pid)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        hours = st.slider(
            f"{name} • Hours per day",
            min_value=1,
            max_value=24,
            value=4,
            key=f"{pid}_ih_hours",
        )
    with c2:
        days = st.slider(
            f"{name} • Days per month",
            min_value=1,
            max_value=31,
            value=20,
            key=f"{pid}_ih_days",
        )
    with c3:
        mobility = st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_ih_mobility",
        )
    default_conditions = st.session_state.get(f"ih_conditions_saved_{pid}", [])
    if default_conditions is None:
        default_conditions = [seeds["chronic_single"]] if seeds["chronic_single"] in {"Diabetes", "Parkinson's"} else []
    ih_conditions = st.multiselect(
        f"{name} • Chronic conditions",
        CONDITION_OPTIONS,
        default=default_conditions,
        format_func=format_condition_label,
        key=f"ih_conditions_{pid}",
        max_selections=5,
    )
    ih_chronic_for_engine = _derive_chronic_for_engine(ih_conditions)
    st.session_state[f"{pid}_ih_chronic"] = ih_chronic_for_engine
    _record_personal_copy(pid, ih_conditions, "ih")
    _union_into_canon(ih_conditions)
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
    c1, c2 = st.columns([1, 1.5])
    with c1:
        level = st.selectbox(
            f"{name} • Memory care level",
            ["Standard", "High Acuity"],
            key=f"{pid}_mc_level",
        )
        mobility = st.selectbox(
            f"{name} • Mobility",
            ["None", "Walker", "Wheelchair"],
            index=["None", "Walker", "Wheelchair"].index(seeds["mobility"]),
            key=f"{pid}_mc_mobility",
        )
    with c2:
        default_conditions = st.session_state.get(f"mc_conditions_saved_{pid}", [])
        if default_conditions is None:
            default_conditions
