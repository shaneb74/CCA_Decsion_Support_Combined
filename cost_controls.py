# cost_controls.py — scenario controls & state-wide location control (single instance)
from __future__ import annotations
from types import SimpleNamespace
import streamlit as st

STATE_FACTORS = {
    "National": 1.0,
    "Washington": 1.15,
    "California": 1.25,
    "Texas": 0.95,
    "Florida": 1.05,
}

MOBILITY_PREFILL_MAP = {
    "Independent": "Independent (no device)",
    "Assisted": "Assisted (cane/walker or needs help)",
    "Non-ambulatory": "Non-ambulatory (wheelchair/bedbound)",
}

def _ensure_defaults():
    st.session_state.setdefault("cost_state", "National")
    st.session_state.setdefault("cost_factor", 1.0)
    st.session_state.setdefault("person_costs", {})
    st.session_state.setdefault("care_overrides", {})
    st.session_state.setdefault("planner_results", {})
    st.session_state.setdefault("mobility_prefill", {})

def render_location_control():
    """Single global Location control (no per-person duplicates)."""
    _ensure_defaults()
    choice = st.selectbox("Location", list(STATE_FACTORS.keys()), index=list(STATE_FACTORS.keys()).index(st.session_state["cost_state"]))
    st.session_state["cost_state"] = choice
    st.session_state["cost_factor"] = float(STATE_FACTORS.get(choice, 1.0))


def _mobility_default_for(pid: str) -> str:
    human = st.session_state.get("mobility_prefill", {}).get(pid, "Independent")
    return MOBILITY_PREFILL_MAP.get(human, MOBILITY_PREFILL_MAP["Independent"])


def render_costs_for_active_recommendations(calculator) -> int:
    """
    For each person:
      - show appropriate cost controls depending on care scenario
      - compute monthly cost via calculator.monthly_cost(inputs)
      - persist per-person totals in st.session_state['person_costs']
    Returns combined total.
    """
    _ensure_defaults()
    combined = 0
    factor = float(st.session_state.get("cost_factor", 1.0))

    # People live on app session_state; import here to avoid cyc dependency
    people = st.session_state.get("people", [])
    planner_results = st.session_state.get("planner_results", {})
    overrides = st.session_state.get("care_overrides", {})

    for p in people:
        pid = p["id"]
        name = p["display_name"]
        rec_obj = planner_results.get(pid)
        if hasattr(rec_obj, "__dict__"):
            scen = (rec_obj.care_type or "none").strip()
        elif isinstance(rec_obj, dict):
            scen = (rec_obj.get("care_type") or "none").strip()
        else:
            scen = "none"
        scen = overrides.get(pid, scen)

        st.subheader(f"{name} — Scenario: {scen.replace('_', ' ').title()}")

        care_level = st.selectbox(
            "Care Level (staffing intensity)",
            ["Low", "Medium", "High"],
            index=["Low", "Medium", "High"].index("High" if scen == "memory_care" else "Medium"),
            key=f"{pid}_care_level",
        )

        # Mobility (carry over)
        mobility_options = [
            "Independent (no device)",
            "Assisted (cane/walker or needs help)",
            "Non-ambulatory (wheelchair/bedbound)",
        ]
        mob_label = st.selectbox(
            "Mobility",
            mobility_options,
            index=mobility_options.index(_mobility_default_for(pid)),
            key=f"{pid}_mobility",
        )
        mobility_map_out = {
            "Independent (no device)": "Independent",
            "Assisted (cane/walker or needs help)": "Assisted",
            "Non-ambulatory (wheelchair/bedbound)": "Non-ambulatory",
        }
        mobility = mobility_map_out[mob_label]

        chronic_options = [
            "None (no ongoing conditions)",
            "Some (1–2 manageable conditions)",
            "Multiple/Complex (several or complex needs)",
        ]
        chronic_map_out = {
            chronic_options[0]: "None",
            chronic_options[1]: "Some",
            chronic_options[2]: "Multiple/Complex",
        }
        chronic_label = st.selectbox(
            "Chronic Conditions",
            chronic_options,
            index=(2 if scen == "memory_care" else 1),
            key=f"{pid}_chronic",
        )
        chronic = chronic_map_out[chronic_label]

        inp = SimpleNamespace(
            care_type=scen,
            care_level=care_level,
            mobility=mobility,
            chronic=chronic,
            state_factor=factor,
        )

        if scen in ("assisted_living", "memory_care"):
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            inp.room_type = room
        elif scen == "in_home":
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            inp.in_home_hours_per_day = int(hours)
            inp.in_home_days_per_month = int(days)
        else:
            # none
            pass

        monthly = int(calculator.monthly_cost(inp))
        st.session_state["person_costs"][pid] = monthly
        st.metric("Estimated Monthly Cost", f"${monthly:,}")
        st.divider()
        combined += monthly

    return int(combined)