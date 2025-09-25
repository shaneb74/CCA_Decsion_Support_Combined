# pages/Plan_for_My_Advisor.py
# Multipage-ready PFMA page. Do NOT call st.set_page_config() here.
# Expected upstream (main app) to set page config and provide session persistence.
# Drop this file into your repo's /pages directory.

import streamlit as st

# --------------------------
# Lightweight helpers
# --------------------------
def get_gc_summary():
    """
    Pull GC outputs from your existing store (session_state or db).
    Return None if GC wasn't completed.
    Expected keys:
      care_path (str), flags (list[str]), zip (str|None)
    """
    return st.session_state.get("gc_summary")


def get_calculator_snapshot():
    """
    Pull Calculator outputs from your existing store.
    Return None if Calculator wasn't completed.
    Expected keys:
      income (dict), benefits (dict), assets (dict),
      monthly_cost (float|int|str), monthly_gap (float|int|str),
      years_funded (float|int|None), payer_hint (str|None)
    """
    return st.session_state.get("calculator_snapshot")


def set_minimal_booking(payload: dict):
    """Persist minimal booking payload (replace with your existing save)."""
    st.session_state["pfma_booking"] = payload


def set_optional_enrichment(payload: dict):
    """Persist optional enrichment payload (replace with your existing save)."""
    st.session_state["pfma_optional"] = payload


def read_only_badges(flags: list[str]):
    if not flags:
        st.caption("No risk flags recorded yet.")
        return
    cols = st.columns(min(4, max(1, len(flags))))
    for i, f in enumerate(flags):
        with cols[i % len(cols)]:
            st.markdown(
                f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;"
                "border:1px solid #e5e7eb;font-size:0.85rem;background:#fafafa;'>"
                f"🛈 {f.replace('_',' ').title()}</div>",
                unsafe_allow_html=True
            )


def metric_safe(label, value):
    try:
        st.metric(label, f"${float(value):,.0f}")
    except Exception:
        st.metric(label, f"{value if value is not None else '—'}")


# --------------------------
# Page content
# --------------------------
st.title("Plan for My Advisor")
st.caption("Schedule a time with an advisor. We'll only ask what we need right now.")

# Progress indicator (simple 2-step)
step = st.session_state.get("pfma_step", 1)
st.progress(0.5 if step == 1 else 1.0, text=f"Step {step} of 2")

# Pull upstream data
gc = get_gc_summary()
calc = get_calculator_snapshot()

# --------------------------
# STEP 1: Booking (minimal)
# --------------------------
if step == 1:
    with st.expander("Your current plan summary", expanded=True):
        if gc:
            st.subheader("Recommendation")
            st.markdown(f"**Suggested path:** {gc.get('care_path','—')}")
            st.caption("Why this path:")
            read_only_badges(gc.get("flags", []))
        else:
            st.info("We don't have a Guided Care Plan on file yet. You can still book now.")

        if calc:
            st.subheader("Budget snapshot")
            col1, col2, col3 = st.columns(3)
            metric_safe("Est. Monthly Cost", calc.get("monthly_cost"))
            metric_safe("Monthly Gap", calc.get("monthly_gap"))
            yf = calc.get('years_funded')
            col3.metric("Years Funded", f"{float(yf):.1f}" if isinstance(yf,(int,float,str)) and str(yf).replace('.','',1).isdigit() else "—")
        else:
            st.info("No Cost Planner data yet. You can add numbers later or try the calculator after booking.")

    st.divider()

    with st.form("pfma_booking"):
        st.subheader("Booking details")

        # Relationship default demo
        rel_default = "Self"
        if gc and st.session_state.get("user_is_proxy"):
            rel_default = st.session_state.get("proxy_relationship", "Family / POA")

        name = st.text_input("Your name", value=st.session_state.get("user_name",""))
        relationship = st.selectbox(
            "Your relationship to the care recipient",
            ["Self","Spouse/Partner","Adult Child","POA/Representative","Other"],
            index=["Self","Spouse/Partner","Adult Child","POA/Representative","Other"].index(rel_default) if rel_default in ["Self","Spouse/Partner","Adult Child","POA/Representative","Other"] else 0
        )
        phone = st.text_input("Best phone number", value=st.session_state.get("user_phone",""), placeholder="+1 (___) ___-____")
        email = st.text_input("Email (optional)", value=st.session_state.get("user_email",""))

        # ZIP prefill from GC if present
        zipcode = st.text_input("ZIP code for care search", value=(gc.get("zip","") if gc else st.session_state.get("zip","")))

        urgency = st.select_slider("When do you need support?", options=["Exploring (3+ months)","Planning (1–3 months)","Soon (2–4 weeks)","ASAP (0–7 days)"], value="Planning (1–3 months)")
        constraints = st.text_area("Any must-haves or constraints? (optional)", placeholder="Pets allowed, near daughter in Seattle, budget cap, wheelchair accessible...")

        payer_hint = None
        if calc and calc.get("payer_hint"):
            payer_hint = st.selectbox("Primary payer (you can adjust)", ["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"], index=["Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"].index(calc["payer_hint"]))
        else:
            payer_hint = st.selectbox("Primary payer (optional)", ["Prefer not to say","Private Pay","LTC Insurance","VA Aid & Attendance","Medicaid"], index=0)

        # Appointment picker placeholder
        slot = st.text_input("Appointment time", placeholder="Select from scheduler widget")

        consent = st.checkbox("I agree to be contacted by an advisor", value=False)

        submitted = st.form_submit_button("Schedule appointment")
        if submitted:
            if not name or not phone or not zipcode or not slot or not consent:
                st.error("Please complete the required fields (name, phone, ZIP, appointment time, consent).")
            else:
                set_minimal_booking({
                    "name": name,
                    "relationship": relationship,
                    "phone": phone,
                    "email": email,
                    "zipcode": zipcode,
                    "urgency": urgency,
                    "constraints": constraints,
                    "payer_hint": payer_hint,
                    "slot": slot,
                    "consent": consent,
                })
                st.session_state["pfma_step"] = 2
                st.rerun()

# --------------------------
# STEP 2: Optional enrichment (after booking)
# --------------------------
if step == 2:
    st.success("You're on the calendar. Share a bit more so we can prepare. Totally optional.")

    # Adaptive finance section: only if Calculator missing
    with st.expander("Financial snapshot (optional)"):
        if calc:
            st.caption("We already have your Cost Planner details. Advisors will review them with you.")
            st.json({
                "payer_hint": calc.get("payer_hint"),
                "income_keys": list((calc.get("income") or {}).keys()),
                "has_assets": bool(calc.get("assets")),
            })
        else:
            budget = st.select_slider("Do you know your realistic monthly care budget?", options=["<$3,000","$3,000–$5,000","$5,000–$8,000",">$8,000"], value="$3,000–$5,000")
            income_sources = st.text_area("Main sources of monthly income (SS, pensions, annuities)", placeholder="Social Security ~$2,100; Pension ~$600")
            benefits = st.multiselect("Benefits that may help with costs", ["VA Aid & Attendance","LTC Insurance","Medicaid"])
            assets = st.text_area("Any assets or savings that may help cover costs", placeholder="Savings ~$25k; Home equity ~—")
            st.caption("Prefer a full breakdown? Try the Cost Planner for detailed numbers and an affordability timeline.")

    with st.expander("Health & care (optional)"):
        health = st.text_area("Tell us about any health conditions or diagnoses we should know about.", placeholder="e.g., Parkinson's, diabetes, memory changes...")
        adls = st.text_area("Are there daily activities where support would help?", placeholder="Bathing, dressing, meals, medication, mobility, continence...")
        mobility = st.text_input("Any mobility equipment or oxygen use?", placeholder="Walker, wheelchair, cane, oxygen (L/min)")
        diet = st.text_input("Any dietary needs or restrictions?", placeholder="Diabetic, low sodium, vegetarian, other")

    with st.expander("Lifestyle & environment (optional)"):
        activities = st.text_area("What activities or hobbies are important to keep in your life?", placeholder="Gardening, church, bingo, walking group...")
        pets_kids = st.text_input("Comfort with pets or children around?", placeholder="Loves small dogs; enjoys kids around in common areas")
        location_pref = st.text_input("Preferred location(s)", placeholder="ZIPs or neighborhoods, proximity to family")

    with st.expander("Current living situation (optional)"):
        living_now = st.selectbox("Where are you living right now?", ["Home","Hospital","Rehab","Skilled Nursing Facility","Other"])
        discharge = st.text_input("Any upcoming discharge or transition dates?", placeholder="e.g., Hospital discharge 2025-10-05")

    if st.button("Save optional details"):
        set_optional_enrichment({
            "finance": {
                "provided_by_calculator": bool(calc),
                "budget_band": locals().get("budget", None) if not calc else None,
                "income_sources": locals().get("income_sources", None) if not calc else None,
                "benefits": locals().get("benefits", None) if not calc else None,
                "assets": locals().get("assets", None) if not calc else None,
            },
            "health": {
                "conditions": locals().get("health", None),
                "adls": locals().get("adls", None),
                "mobility": locals().get("mobility", None),
                "diet": locals().get("diet", None),
            },
            "lifestyle": {
                "activities": locals().get("activities", None),
                "pets_kids": locals().get("pets_kids", None),
                "location_pref": locals().get("location_pref", None),
            },
            "living": {
                "living_now": locals().get("living_now", None),
                "discharge": locals().get("discharge", None),
            }
        })
        st.success("Details saved. Your advisor will review them before your call.")
        st.balloons()
