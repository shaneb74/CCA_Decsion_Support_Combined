# cost_controls.py — single location control + per-person cost configuration
from __future__ import annotations

from types import SimpleNamespace
import streamlit as st

# Notes:
# - UI NEVER does math. It only collects inputs and calls calculator.monthly_cost(inputs).
# - For care_type == "none", we call the engine and store 0; no UI controls are shown.
# - Location selector is rendered ONCE via render_location_control(); do not duplicate it elsewhere.


def _mobility_prefill_from_flags(flags: set[str]) -> str:
    """
    Map flags to a default Mobility UI choice.
    """
    if "high_mobility_dependence" in flags:
        return "Non-ambulatory"
    if "moderate_mobility" in flags:
        return "Assisted"
    return "Independent"


def render_location_control():
    """
    Single shared Location control. Stores selected state in st.session_state['cost_state'] via the widget key.
    """
    states = ["National", "Washington", "California", "Texas", "Florida"]
    default_state = st.session_state.get("cost_state", "National")
    try:
        default_index = states.index(default_state) if default_state in states else 0
    except Exception:
        default_index = 0

    # IMPORTANT: let Streamlit own the widget state; don't assign to st.session_state manually.
    st.selectbox(
        "Location",
        states,
        index=default_index,
        key="cost_state",
        help="Adjusts for typical market rates in the selected state.",
    )


def render_costs_for_active_recommendations(
    *,
    calculator,
    people: list[dict],
    planner_results: dict,
    care_overrides: dict,
) -> int:
    """
    Renders cost controls for each person based on the active scenario (override else recommendation),
    calls calculator.monthly_cost(inputs), and stores results in st.session_state['person_costs'].
    Returns combined total.
    """
    st.session_state.person_costs = st.session_state.get("person_costs", {})
    combined_total = 0
    state = st.session_state.get("cost_state", "National")

    # Pretty labels
    nice = {
        "none": "None",
        "in_home": "In-home Care",
        "assisted_living": "Assisted Living",
        "memory_care": "Memory Care",
    }

    for p in people:
        pid = p["id"]
        name = p["display_name"]

        rec = planner_results.get(pid)
        # rec can be a dataclass (PlannerResult) or dict (older runs)
        if hasattr(rec, "care_type"):
            care_type_rec = rec.care_type
            flags = set(rec.flags or [])
        elif isinstance(rec, dict):
            care_type_rec = rec.get("care_type", "in_home")
            flags = set(rec.get("flags", []))
        else:
            care_type_rec = "in_home"
            flags = set()

        scen = (care_overrides.get(pid, care_type_rec) or "in_home").strip()

        st.subheader(f"{name} — Scenario: {nice.get(scen, scen).title()}")

        # ----- Scenario: NONE (engine is the single source of truth) -----
        if scen in ("none", "", None):
            inp = SimpleNamespace(state=state, care_type="none")
            try:
                monthly = calculator.monthly_cost(inp)  # engine should return 0 for 'none'
            except Exception:
                monthly = 0
            st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
            st.session_state.person_costs[pid] = int(monthly)
            st.divider()
            combined_total += int(monthly)
            continue

        # ----- Common context for AL/MC drop-downs -----
        care_levels = ["Low", "Medium", "High"]
        rooms = ["Studio", "1 Bedroom", "Shared"]
        mobility_choices = ["Independent", "Assisted", "Non-ambulatory"]
        chronic_choices = ["None", "Some", "Multiple/Complex"]

        # derive prefill from flags (carry-over)
        mobility_prefill = _mobility_prefill_from_flags(flags)

        # ----- Scenario: IN-HOME (sliders) -----
        if scen == "in_home":
            # hours/day and days/month sliders; defaults 4 and 20
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")

            # Let user still indicate mobility/chronic for pricing models that use them
            mob_label = st.selectbox(
                "Mobility",
                mobility_choices,
                index=mobility_choices.index(mobility_prefill),
                key=f"{pid}_mobility_inhome",
            )
            chr_label = st.selectbox(
                "Chronic Conditions",
                chronic_choices,
                index=1,  # default "Some"
                key=f"{pid}_chronic_inhome",
            )

            inp = SimpleNamespace(
                state=state,
                care_type="in_home",
                in_home_hours_per_day=int(hours),
                in_home_days_per_month=int(days),
                mobility=mob_label,
                chronic=chr_label,
            )

        # ----- Scenario: ASSISTED LIVING (dropdowns) -----
        elif scen == "assisted_living":
            care_level = st.selectbox(
                "Care Level (staffing intensity)",
                care_levels,
                index=1 if "severe_cognitive_risk" in flags else 1,
                key=f"{pid}_care_level_al",
            )
            room = st.selectbox(
                "Room Type",
                rooms,
                index=0,
                key=f"{pid}_room_al",
            )
            mob_label = st.selectbox(
                "Mobility",
                mobility_choices,
                index=mobility_choices.index(mobility_prefill),
                key=f"{pid}_mobility_al",
            )
            chr_label = st.selectbox(
                "Chronic Conditions",
                chronic_choices,
                index=2 if "severe_cognitive_risk" in flags else 1,
                key=f"{pid}_chronic_al",
            )

            inp = SimpleNamespace(
                state=state,
                care_type="assisted_living",
                care_level=care_level,
                room_type=room,
                mobility=mob_label,
                chronic=chr_label,
            )

        # ----- Scenario: MEMORY CARE (dropdowns) -----
        elif scen == "memory_care":
            care_level = st.selectbox(
                "Care Level (staffing intensity)",
                care_levels,
                index=2,  # default to High
                key=f"{pid}_care_level_mc",
            )
            room = st.selectbox(
                "Room Type",
                rooms,
                index=0,
                key=f"{pid}_room_mc",
            )
            mob_label = st.selectbox(
                "Mobility",
                mobility_choices,
                index=mobility_choices.index(mobility_prefill),
                key=f"{pid}_mobility_mc",
            )
            chr_label = st.selectbox(
                "Chronic Conditions",
                chronic_choices,
                index=2,  # Multiple/Complex by default for MC
                key=f"{pid}_chronic_mc",
            )

            inp = SimpleNamespace(
                state=state,
                care_type="memory_care",
                care_level=care_level,
                room_type=room,
                mobility=mob_label,
                chronic=chr_label,
            )

        else:
            # Unknown label — treat as in_home gracefully
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours_fallback")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days_fallback")
            inp = SimpleNamespace(
                state=state,
                care_type="in_home",
                in_home_hours_per_day=int(hours),
                in_home_days_per_month=int(days),
            )

        # Compute monthly cost strictly via engine
        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            monthly = 0

        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        st.session_state.person_costs[pid] = int(monthly)
        st.divider()
        combined_total += int(monthly)

    return int(combined_total)