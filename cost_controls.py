# cost_controls.py  — single source of truth for location + per-person cost widgets
from __future__ import annotations
import streamlit as st

# ------- Public: Location control (render once) -------
def render_location_control():
    """
    Renders a single, global Location selector and stores it ONLY via the widget key.
    Returns the selected label and a float multiplier.
    """
    options = ["National", "Washington", "California", "Texas", "Florida"]
    multipliers = {
        "National": 1.00,
        "Washington": 1.15,
        "California": 1.25,
        "Texas": 0.95,
        "Florida": 1.05,
    }

    # IMPORTANT: never assign st.session_state.cost_state manually;
    # let the widget own this key so we don't fight Streamlit.
    default_idx = 0
    if "cost_state" in st.session_state and st.session_state["cost_state"] in options:
        default_idx = options.index(st.session_state["cost_state"])

    choice = st.selectbox(
        "Location",
        options,
        index=default_idx,
        key="cost_state",  # widget manages the state
        help="Adjusts typical market rates for the selected state."
    )
    return choice, multipliers.get(choice, 1.00)

# ------- Public: Cost controls for active recommendations -------
def render_costs_for_active_recommendations():
    """
    Reads people + recommendations from session_state and renders
    the per-person cost controls (scenarios and their widgets). 
    Returns the combined total.
    """
    people = st.session_state.get("people", [])
    recs   = st.session_state.get("planner_results", {})
    overrides = st.session_state.get("care_overrides", {})
    person_costs = st.session_state.setdefault("person_costs", {})

    # Location chosen once globally (idempotent — safe to call)
    state_label = st.session_state.get("cost_state", "National")
    _, multiplier = render_location_control()

    combined = 0

    # Options display names
    nice = {
        "none": "None",
        "in_home": "In-home Care",
        "assisted_living": "Assisted Living",
        "memory_care": "Memory Care",
    }

    # Collect updates without applying them yet
    updates = {}
    for p in people:
        pid = p["id"]
        name = p["display_name"]
        rec = recs.get(pid)

        # derive scenario
        scen = (overrides.get(pid) or (getattr(rec, "care_type", None) if rec else None) or "none").strip()

        st.subheader(f"{name} — Scenario: {nice.get(scen, scen).title()}")

        # Let user switch scenarios here (e.g., healthy partner → "None" or "In-home")
        options = ["none", "in_home", "assisted_living", "memory_care"]
        idx = options.index(scen) if scen in options else 0
        label = st.selectbox(
            f"Care scenario for {name}",
            [nice[o] for o in options],
            index=idx,
            key=f"calc_override_{pid}",
        )
        reverse = {v: k for k, v in nice.items()}
        new_scen = reverse.get(label, "none")
        updates[pid] = new_scen

        # Pre-fill mobility from planner flags if available
        mobility_prefill = "Independent"
        if rec and hasattr(rec, "flags"):
            flags = set(rec.flags)
            if "high_mobility_dependence" in flags:
                mobility_prefill = "Non-ambulatory"
            elif "moderate_mobility" in flags:
                mobility_prefill = "Assisted"

        # Scenario-specific controls
        if new_scen in ("assisted_living", "memory_care"):
            # Keep dropdowns (NOT sliders) here
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            care_level = st.selectbox("Care Level (staffing intensity)", ["Low", "Medium", "High"], key=f"{pid}_care_level")
            chronic = st.selectbox("Chronic Conditions", ["None", "Some", "Multiple/Complex"], key=f"{pid}_chronic")
            mobility = st.selectbox(
                "Mobility",
                ["Independent", "Assisted", "Non-ambulatory"],
                index=["Independent", "Assisted", "Non-ambulatory"].index(mobility_prefill),
                key=f"{pid}_mobility"
            )
            # Estimate base
            base = 6500 if new_scen == "assisted_living" else 8500
            # Simple modifiers
            care_bump = {"Low": 0, "Medium": 400, "High": 900}[care_level]
            chronic_bump = {"None": 0, "Some": 200, "Multiple/Complex": 600}[chronic]
            mob_bump = {"Independent": 0, "Assisted": 200, "Non-ambulatory": 600}[mobility]
            room_bump = {"Studio": 0, "1 Bedroom": 700, "Shared": -500}[room]
            monthly = int((base + care_bump + chronic_bump + mob_bump + room_bump) * multiplier)

        elif new_scen == "in_home":
            # Keep sliders here with defaults 4 / 20
            hours = st.slider("Hours per day", min_value=0, max_value=24, value=4, step=1, key=f"{pid}_hours_per_day")
            days  = st.slider("Days per month", min_value=0, max_value=31, value=20, step=1, key=f"{pid}_days_per_month")
            mobility = st.selectbox(
                "Mobility",
                ["Independent", "Assisted", "Non-ambulatory"],
                index=["Independent", "Assisted", "Non-ambulatory"].index(mobility_prefill),
                key=f"{pid}_inhome_mobility"
            )
            rate = {"Independent": 28, "Assisted": 32, "Non-ambulatory": 38}[mobility]
            monthly = int(hours * days * rate * multiplier)

        else:  # none
            monthly = 0

        st.metric("Estimated Monthly Cost", f"${monthly:,.0f}")
        person_costs[pid] = monthly  # Update person_costs directly, safe during render
        combined += monthly
        st.divider()

    # Apply overrides only after all widgets are rendered
    if st.button("Apply Changes"):
        for pid, scen in updates.items():
            st.session_state.care_overrides[pid] = scen

    return combined