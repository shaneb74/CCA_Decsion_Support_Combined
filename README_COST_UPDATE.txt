INSTALL / UPDATE
================

This zip contains a single new module:

  • cost_controls.py   — Cost Planner UI + calculator handoff

WHY
---
Your Cost Planner controls were collecting values but not feeding them to
CalculatorEngine in a structured way. The engine then returned a flat default
(typically 6500), so changing any dropdown/slider didn't move the needle.

WHAT TO DO
----------
1) Drop cost_controls.py in your project ROOT (same folder as app.py).

2) Open app.py and ensure the imports include:
       import cost_controls

3) Replace ONLY the 'calculator' step with the block below:

    # CALCULATOR
    elif st.session_state.step == "calculator":
        st.header("Cost Planner")
        # ONE location control for the whole plan
        cost_controls.render_location_control()

        combined_total = cost_controls.render_costs_for_active_recommendations(
            planner=planner,
            calculator=calculator,
        )

        st.subheader("Combined Total")
        st.metric("Estimated Combined Monthly Cost", f"${combined_total:,.0f}")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Back to recommendations"):
                st.session_state.step = "recommendations"
                st.rerun()
        with c2:
            if st.button("Add Household & Assets"):
                st.session_state.step = "household"
                st.rerun()
        with c3:
            if st.button("Finish"):
                st.session_state.step = "intro"
                st.rerun()

NOTES
-----
• There is exactly ONE location control now. It persists in st.session_state.cost_state.
• For each person, scenario-specific controls appear:
    - Assisted Living: Care Level, Room Type, Mobility, Chronic Conditions (all dropdowns)
    - In-Home: Hours/day and Days/month sliders + Conditions dropdown
    - Memory Care: Care Level + Conditions dropdown
• The module builds a single 'inputs' object and calls
      calculator.monthly_cost(inputs)
  so your engine can compute the true price. The result is stored in
      st.session_state.person_costs[pid]
  and the combined total updates immediately.

No other files need to change.
