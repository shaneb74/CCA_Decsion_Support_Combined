
import streamlit as st

def render_pfma():
    st.title("Plan for My Advisor")
    st.caption("Schedule a time with an advisor. We'll only ask what we need right now.")

    # Context pulled from session if present
    gc = st.session_state.get("gc_summary", {})
    calc = st.session_state.get("calculator_snapshot")

    with st.expander("Your current plan summary", expanded=True):
        if gc:
            st.subheader("Recommendation")
            st.markdown(f"**Suggested path:** {gc.get('care_path','—')}")
            flags = gc.get("flags") or []
            if flags:
                cols = st.columns(min(4, max(1, len(flags))))
                for i, f in enumerate(flags):
                    with cols[i % len(cols)]:
                        st.markdown(
                            f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;"
                            "border:1px solid #e5e7eb;font-size:0.85rem;background:#fafafa;'>"
                            f"🛈 {str(f).replace('_',' ').title()}</div>",
                            unsafe_allow_html=True
                        )
        else:
            st.info("No Guided Care Plan found. You can still book now.")

        if calc:
            st.subheader("Budget snapshot")
            c1, c2, c3 = st.columns(3)
            try:
                c1.metric("Est. Monthly Cost", f"${float(calc.get('monthly_cost', 0)):,.0f}")
            except Exception:
                c1.metric("Est. Monthly Cost", calc.get('monthly_cost', '—'))
            try:
                c2.metric("Monthly Gap", f"${float(calc.get('monthly_gap', 0)):,.0f}")
            except Exception:
                c2.metric("Monthly Gap", calc.get('monthly_gap', '—'))
            yf = calc.get("years_funded")
            c3.metric("Years Funded", f"{float(yf):.1f}" if isinstance(yf,(int,float)) else "—")
        else:
            st.info("No Cost Planner data yet.")

    st.divider()

    # Booking form
    with st.form("pfma_booking"):
        st.subheader("Booking details")

        name = st.text_input("Your name", value=st.session_state.get("user_name",""))
        relationship = st.selectbox("Your relationship to the care recipient",
                                    ["Self","Spouse/Partner","Adult Child","POA/Representative","Other"], index=0)
        phone = st.text_input("Best phone number", value=st.session_state.get("user_phone",""),
                              placeholder="+1 (___) ___-____")
        email = st.text_input("Email (optional)", value=st.session_state.get("user_email",""))
        zipcode = st.text_input("ZIP code for care search", value=(gc.get("zip","") if isinstance(gc, dict) else ""))
        urgency = st.select_slider("When do you need support?",
                    options=["Exploring (3+ months)","Planning (1–3 months)","Soon (2–4 weeks)","ASAP (0–7 days)"],
                    value="Planning (1–3 months)")
        constraints = st.text_area("Any must-haves or constraints? (optional)")

        if calc and calc.get("payer_hint"):
            payer_hint = st.selectbox("Primary payer (you can adjust)",
                                      ["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"],
                                      index=["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"].index(calc["payer_hint"]))
        else:
            payer_hint = st.selectbox("Primary payer (optional)",
                                      ["Prefer not to say","Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"],
                                      index=0)

        slot = st.text_input("Appointment time", placeholder="Select from scheduler widget")
        consent = st.checkbox("I agree to be contacted by an advisor", value=False)

        submitted = st.form_submit_button("Schedule appointment")
        if submitted:
            if not name or not phone or not zipcode or not slot or not consent:
                st.error("Please complete the required fields.")
            else:
                st.success("Appointment scheduled! You're on the calendar.")
                st.session_state["pfma_step"] = "optional"
                st.session_state["pfma_booking"] = {
                    "name": name, "relationship": relationship, "phone": phone, "email": email,
                    "zipcode": zipcode, "urgency": urgency, "constraints": constraints,
                    "payer_hint": payer_hint, "slot": slot, "consent": consent
                }

    # Optional enrichment
    if st.session_state.get("pfma_step") == "optional":
        st.success("Share a bit more so we can prepare. Totally optional.")

        with st.expander("Financial snapshot (optional)"):
            if calc:
                st.caption("We already have your Cost Planner details.")
            else:
                budget = st.select_slider("Do you know your realistic monthly care budget?",
                                          options=["<$3,000","$3,000–$5,000","$5,000–$8,000",">$8,000"],
                                          value="$3,000–$5,000")
                income_sources = st.text_area("Main sources of monthly income")
                benefits = st.multiselect("Benefits that may help with costs",
                                          ["VA Aid & Attendance","LTC Insurance","Medicaid"])
                assets = st.text_area("Any assets or savings that may help cover costs")
                st.session_state["pfma_optional_finance"] = {
                    "budget_band": budget, "income_sources": income_sources,
                    "benefits": benefits, "assets": assets
                }

        with st.expander("Health & care (optional)"):
            st.text_area("Tell us about any health conditions or diagnoses we should know about.")
            st.text_area("Are there daily activities where support would help?")
            st.text_input("Any mobility equipment or oxygen use?")
            st.text_input("Any dietary needs or restrictions?")

        with st.expander("Lifestyle & environment (optional)"):
            st.text_area("What activities or hobbies are important to keep in your life?")
            st.text_input("Comfort with pets or children around?")
            st.text_input("Preferred location(s)")

        with st.expander("Current living situation (optional)"):
            st.selectbox("Where are you living right now?",
                         ["Home","Hospital","Rehab","Skilled Nursing Facility","Other"])
            st.text_input("Any upcoming discharge or transition dates?")

        if st.button("Save optional details"):
            st.success("Details saved. Your advisor will review them before your call.")
            st.balloons()

if __name__ == "__main__":
    render_pfma()
