# cost_controls.py — single location control + per-person cost controls
from __future__ import annotations
from typing import Dict, Any, List, Tuple
from types import SimpleNamespace
import streamlit as st

# ===== One location selector for the whole page =====
_LOCATIONS = ["National", "Washington", "California", "Texas", "Florida"]
_FACTORS = {"National": 1.00, "Washington": 1.15, "California": 1.25, "Texas": 0.95, "Florida": 1.05}


def render_location_control() -> float:
    """Renders a single location selector and stores both state & factor once."""
    if "cost_state" not in st.session_state:
        st.session_state.cost_state = "National"
    default_idx = _LOCATIONS.index(st.session_state.cost_state) if st.session_state.cost_state in _LOCATIONS else 0
    choice = st.selectbox("Location", _LOCATIONS, index=default_idx, key="cost_state_select")
    st.session_state.cost_state = choice
    factor = _FACTORS.get(choice, 1.0)
    st.session_state.cost_factor = factor
    return factor


# ===== Carry-over defaults from flags to cost UI =====
def carryover_defaults(flags: List[str]) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "mobility": "Independent",
        "care_level": "Medium",
        "chronic": "Some",
        "room_type": "Studio",
        "in_home_hours_per_day": 4,
        "in_home_days_per_month": 20,
    }
    fset = set(flags or [])
    if "high_mobility_dependence" in fset:
        defaults["mobility"] = "Non-ambulatory"
    elif "moderate_mobility" in fset:
        defaults["mobility"] = "Assisted"

    if "severe_cognitive_risk" in fset:
        defaults["care_level"] = "High"
    return defaults


# ===== Compute monthly (lightweight, local multipliers so UI reacts) =====
def _compute_monthly(care_type: str, sel: Dict[str, Any], factor: float) -> int:
    base = {"none": 0, "in_home": 28 * 30, "assisted_living": 6000, "memory_care": 8000}  # in_home base ignored; see sliders

    if care_type == "in_home":
        hours = int(sel.get("in_home_hours_per_day", 4))
        days  = int(sel.get("in_home_days_per_month", 20))
        # $30/hr baseline (scaled by factor)
        monthly = int(hours * days * 30 * factor)
        return monthly

    # Assisted living / Memory care adjustments
    monthly = int(base.get(care_type, 0) * factor)

    care_level = sel.get("care_level", "Medium")
    room_type  = sel.get("room_type", "Studio")
    mobility   = sel.get("mobility", "Independent")
    chronic    = sel.get("chronic", "Some")

    care_add = {"Low": -300, "Medium": 0, "High": 500}.get(care_level, 0)
    room_add = {"Shared": -600, "Studio": 0, "1 Bedroom": 800}.get(room_type, 0)
    mob_add  = {"Independent": 0, "Assisted": 200, "Non-ambulatory": 400}.get(mobility, 0)
    chr_add  = {"None": 0, "Some": 150, "Multiple/Complex": 400}.get(chronic, 0)

    monthly = int((monthly + care_add + room_add + mob_add + chr_add))
    return max(0, monthly)


# ===== Cost UI per person =====
def _render_person_cost_controls(person: Dict[str, Any], rec: Any, overrides: Dict[str, str], factor: float) -> Tuple[int, str]:
    pid = person["id"]; name = person["display_name"]
    recommended = getattr(rec, "care_type", None) if hasattr(rec, "care_type") else (rec.get("care_type") if isinstance(rec, dict) else "in_home")
    care_type = overrides.get(pid, recommended or "in_home")

    st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()}")

    # Carryover defaults from flags
    flags = getattr(rec, "flags", []) if hasattr(rec, "flags") else (rec.get("flags", []) if isinstance(rec, dict) else [])
    defaults = carryover_defaults(flags)

    # Scenario switcher — always allow none/in-home/AL/memory
    options = {"none": "No care needed", "in_home": "In-home care", "assisted_living": "Assisted living", "memory_care": "Memory care"}
    sel_label = st.selectbox("Choose a cost scenario", list(options.values()), index=list(options).index(care_type), key=f"scenario_{pid}")
    care_type = list(options.keys())[list(options.values()).index(sel_label)]
    overrides[pid] = care_type  # persist

    sel: Dict[str, Any] = {}

    if care_type == "in_home":
        # sliders only (narrow, precise)
        hours = st.slider("Hours per day", 0, 24, int(defaults["in_home_hours_per_day"]), 1, key=f"{pid}_hours")
        days  = st.slider("Days per month", 0, 31, int(defaults["in_home_days_per_month"]), 1, key=f"{pid}_days")
        sel["in_home_hours_per_day"] = int(hours)
        sel["in_home_days_per_month"] = int(days)

        # Optional context from flags as caption
        if "high_mobility_dependence" in (flags or []) or "moderate_mobility" in (flags or []):
            st.caption("Mobility support noted in your care plan has been carried over to costs.")

    elif care_type in ("assisted_living", "memory_care"):
        care_level = st.selectbox("Care level (staffing)", ["Low", "Medium", "High"], index=["Low","Medium","High"].index(defaults["care_level"]), key=f"{pid}_care_level")
        room_type  = st.selectbox("Apartment type", ["Shared", "Studio", "1 Bedroom"], index=["Shared","Studio","1 Bedroom"].index(defaults["room_type"]), key=f"{pid}_room")
        mobility   = st.selectbox("Mobility", ["Independent", "Assisted", "Non-ambulatory"], index=["Independent","Assisted","Non-ambulatory"].index(defaults["mobility"]), key=f"{pid}_mob")
        chronic    = st.selectbox("Chronic conditions", ["None", "Some", "Multiple/Complex"], index=["None","Some","Multiple/Complex"].index(defaults["chronic"]), key=f"{pid}_chr")

        sel.update({"care_level": care_level, "room_type": room_type, "mobility": mobility, "chronic": chronic})

    # Compute monthly locally (reactive), store for breakdown
    monthly = _compute_monthly(care_type, sel, factor)
    st.metric("Estimated monthly cost", f"${monthly:,.0f}")
    st.divider()

    # Save person costs in session for breakdown step
    st.session_state.setdefault("person_costs", {})
    st.session_state["person_costs"][pid] = int(monthly)

    return int(monthly), care_type


def render_costs_for_active_recommendations(
    *,
    planner_results: Dict[str, Any] | None = None,
    overrides: Dict[str, str] | None = None,
    factor: float | None = None
) -> int:
    """Render per-person cost controls for the active (or overridden) scenarios, return combined total."""
    people: List[Dict[str, Any]] = st.session_state.get("people", [])
    if planner_results is None:
        planner_results = st.session_state.get("planner_results", {})
    if overrides is None:
        overrides = st.session_state.get("care_overrides", {})
    if factor is None:
        factor = st.session_state.get("cost_factor", 1.0)

    combined = 0
    for p in people:
        pid = p["id"]
        rec = planner_results.get(pid, {"care_type": "in_home", "flags": []})
        subtotal, care_type = _render_person_cost_controls(p, rec, overrides, factor)
        combined += int(subtotal)

    st.subheader("Combined total")
    st.metric("Estimated combined monthly cost", f"${combined:,.0f}")
    # persist overrides back
    st.session_state["care_overrides"] = overrides
    return int(combined)