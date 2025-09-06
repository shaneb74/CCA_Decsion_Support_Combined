# app.py — Senior Navigator (Planner → Recommendation → Costs → Household)
# All JSON files and code live in the repo root. Assets drawers live in asset_engine.

from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

# ---------- Page config ----------
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")

# ---------- Paths (root) ----------
ROOT = Path(__file__).resolve().parent
QA_PATH  = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ---------- Engines ----------
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

try:
    import asset_engine  # your drawers live here
except Exception:
    asset_engine = None  # optional

# ---------- Init engines ----------
for p in (QA_PATH, REC_PATH):
    if not p.exists():
        st.error(f"Missing required file: {p.name}")
        st.stop()

try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()


# ---------- Helpers ----------
def make_inputs(**kwargs):
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def reset_all():
    for k in list(st.session_state.keys()):
        if not k.startswith("_"):
            del st.session_state[k]
    st.session_state.step = "intro"


def order_answer_map(amap):
    """Return (ordered_keys, ordered_labels) whether keys are '1','2',... or arbitrary strings."""
    if not isinstance(amap, dict) or not amap:
        return [], []
    keys = list(amap.keys())

    def _is_intlike(x):
        try:
            int(str(x))
            return True
        except Exception:
            return False

    if all(_is_intlike(k) for k in keys):
        ordered_keys = [str(k) for k in sorted(int(str(k)) for k in keys)]
    else:
        ordered_keys = [str(k) for k in sorted(map(str, keys))]
    ordered_labels = [amap[k] for k in ordered_keys]
    return ordered_keys, ordered_labels


def radio_from_answer_map(label, amap, *, key, help_text=None, default_key=None):
    """Render a radio from a JSON answer map and return the SELECTED KEY (string)."""
    ok, ol = order_answer_map(amap)
    if not ol:
        return default_key
    if default_key is not None and str(default_key) in ok:
        idx = ok.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ol, index=idx, key=key, help=help_text)
    return ok[ol.index(sel_label)]


# ---------- Session ----------
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Household")
st.sidebar.button("Start over", on_click=reset_all)


# ===================== Flow =====================

# ----- Intro -----
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown(
        "Choosing senior living or in-home support can feel overwhelming. "
        "This tool breaks it into clear steps.\n\n"
        "1. Answer quick care questions → we recommend a care type.  \n"
        "2. Review costs for that scenario (you can switch it).  \n"
        "3. Add income, benefits, and assets to see affordability.  \n"
        "4. View a detailed breakdown you can save or revisit."
    )
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# ----- Audience -----
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio(
        "Select one:",
        ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"],
        key="aud_role",
    )

    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people = [
            {"id": "A", "display_name": n1, "relationship": "parent"},
            {"id": "B", "display_name": n2, "relationship": "parent"},
        ]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}[
            role
        ]
        people = [{"id": "A", "display_name": n, "relationship": rel}]

    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.planner_results = {}
        # Interstitial only when single audience and not "Both parents"
        st.session_state.step = "partner_interstitial" if (role != "Both parents" and len(people) == 1) else "planner"
        st.rerun()

# ----- Partner Interstitial (only for single person audience) -----
elif st.session_state.step == "partner_interstitial":
    peeps = st.session_state.get("people", [])
    single = len(peeps) == 1
    primary = peeps[0]["display_name"] if peeps else "Person A"

    st.header("Before we begin")
    st.markdown(
        f"If **{primary}** needs assisted living or memory care, their spouse/partner may also "
        f"need some in-home help. You can include a simple support plan for them now so the "
        f"household picture is complete."
    )

    add = st.checkbox("Yes, I want to evaluate a plan for a spouse/partner", key="care_partner_add")
    if add:
        st.text_input("Spouse/partner name", value="", placeholder="Enter spouse/partner name", key="care_partner_name")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"No, let's just plan for {primary}"):
            st.session_state.step = "planner"
            st.rerun()
    with c2:
        if st.button("Add spouse/partner and continue", disabled=not st.session_state.get("care_partner_add", False)):
            if single and st.session_state.get("care_partner_add"):
                st.session_state.people.append(
                    {
                        "id": "B",
                        "display_name": st.session_state.get("care_partner_name") or "Spouse/Partner",
                        "relationship": "spouse",
                    }
                )
            st.session_state.step = "planner"
            st.rerun()

# ----- Planner (one question at a time per person) -----
elif st.session_state.step == "planner":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not people or i >= len(people):
        st.session_state.step = "recommendations"
        st.rerun()

    person = people[i]
    name = person["display_name"]
    st.header(f"Care Plan Questions for {name}")
    st.caption(f"Person {i+1} of {len(people)}")

    qa = planner.qa or {}
    questions = qa.get("questions", [])
    cond_cfg = qa.get("conditional_questions")

    # one-question-at-a-time index
    wkey = f"qidx_{person['id']}"
    if wkey not in st.session_state:
        st.session_state[wkey] = 0

    idx = st.session_state[wkey]
    total = len(questions)
    idx = max(0, min(idx, total - 1))
    st.progress((idx + 1) / max(1, total))

    answers = st.session_state.answers.get(person["id"], {})

    # render current question
    q = questions[idx]
    amap = q.get("answers", {})
    ordered_keys, ordered_labels = order_answer_map(amap)
    default_key = ordered_keys[0] if ordered_keys else None

    sel_key = radio_from_answer_map(
        f"{q.get('question','Question')} (for {name})",
        amap,
        key=f"{person['id']}_q{idx+1}",
        help_text=q.get("help"),
        default_key=default_key,
    )
    # store INT option key using 1-based q index
    if sel_key is not None:
        try:
            answers[f"q{idx+1}"] = int(sel_key)
        except Exception:
            # if keys are not numeric, still store as string
            answers[f"q{idx+1}"] = sel_key
    st.session_state.answers[person["id"]] = answers

    # nav buttons
    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        if st.button("Back", disabled=(idx == 0)):
            st.session_state[wkey] = max(0, idx - 1)
            st.rerun()
    with b2:
        if st.button("Next", disabled=(idx >= total - 1)):
            st.session_state[wkey] = min(total - 1, idx + 1)
            st.rerun()
    with b3:
        # Finish only on last question
        if st.button("Finish", disabled=(idx != total - 1)):
            try:
                res = planner.run(answers, name=name)  # <— correct signature
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc())
                st.stop()

            st.session_state.planner_results[person["id"]] = {
                "care_type": res.care_type,
                "flags": set(res.flags),
                "scores": res.scores,
                "reasons": res.reasons,
                "advisory": res.narrative,
                "raw_rule": res.raw_rule,
            }

            # reset q index for next person
            st.session_state[wkey] = 0

            # If there's a next person, show transition screen
            if i + 1 < len(people):
                st.session_state.current_person = i + 1
                st.session_state.step = "person_transition"
                st.rerun()
            else:
                st.session_state.step = "recommendations"
                st.rerun()

# ----- Interstitial between persons -----
elif st.session_state.step == "person_transition":
    people = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if i >= len(people):
        st.session_state.step = "recommendations"; st.rerun()
    name = people[i]["display_name"]
    st.header("Great — first plan saved.")
    st.info(f"Now let’s assess **{name}**.")
    if st.button("Start {name}'s care plan"):
        st.session_state.step = "planner"
        st.rerun()

# ----- Recommendations -----
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    st.caption("Start with the recommended scenario, or switch without redoing questions.")

    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})

        care_type = rec.get("care_type", "in_home")
        reasons   = rec.get("reasons", [])
        narrative = rec.get("advisory") or rec.get("message") or rec.get("narrative")

        nice = {
            "none": "None",
            "in_home": "In-home Care",
            "assisted_living": "Assisted Living",
            "memory_care": "Memory Care",
        }
        st.subheader(f"{name}: {nice.get(care_type, care_type).title()} (recommended)")
        if reasons:
            for r in reasons[:5]:
                st.write("• " + str(r))
        if narrative:
            st.info(narrative)

        # allow override
        options = ["none", "in_home", "assisted_living", "memory_care"]
        idx = options.index(care_type) if care_type in options else 1
        label = st.selectbox(
            f"Care scenario for {name}",
            [nice[o] for o in options],
            index=idx,
            key=f"override_{pid}",
        )
        reverse = {v: k for k, v in nice.items()}
        st.session_state.setdefault("care_overrides", {})[pid] = reverse[label]

        st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to questions"):
            st.session_state.step = "planner"; st.rerun()
    with c2:
        if st.button("See Costs"):
            st.session_state.step = "calculator"; st.rerun()

# ----- Calculator -----
elif st.session_state.step == "calculator":
    st.header("Cost Planner")

    # simple geographic factor
    state = st.selectbox("Location", ["National", "Washington", "California", "Texas", "Florida"])
    factor = {"National": 1.0, "Washington": 1.15, "California": 1.25, "Texas": 0.95, "Florida": 1.05}[state]

    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]; name = p["display_name"]
        rec = st.session_state.planner_results.get(pid, {})
        care_type = st.session_state.get("care_overrides", {}).get(pid, rec.get("care_type", "in_home"))

        st.subheader(f"{name} — Scenario: {care_type.replace('_',' ').title()}")

        # Simple inputs; you can extend as needed (room_type, mobility, etc.)
        inp = make_inputs(state=state, care_type=care_type)

        try:
            monthly = int(calculator.monthly_cost(inp) * factor)
        except Exception:
            st.error("CalculatorEngine failed.")
            st.code(traceback.format_exc())
            st.stop()

        st.metric("Estimated Monthly Cost", f"${monthly:,.0f}")
        st.session_state.setdefault("person_costs", {})[pid] = monthly
        total += monthly
        st.divider()

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${total:,.0f}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to recommendations"):
            st.session_state.step = "recommendations"; st.rerun()
    with c2:
        if st.button("Add Household & Assets (optional)"):
            st.session_state.step = "household"; st.rerun()

# ----- Household drawers (external engine) -----
elif st.session_state.step == "household":
    st.header("Household & Budget (optional)")
    st.markdown("Add income, benefits, assets, home decisions, and other costs to see affordability. You can skip this.")

    if asset_engine and hasattr(asset_engine, "render_household_drawers"):
        try:
            result = asset_engine.render_household_drawers(st)  # returns a HouseholdResult-like object
            if result and hasattr(result, "monthly_total"):
                st.metric("Estimated Monthly Impact (from drawers)", f"${int(result.monthly_total):,}")
        except Exception:
            st.error("Household drawers failed.")
            st.code(traceback.format_exc())
    else:
        st.info("Household drawers module not available in this build.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Costs"):
            st.session_state.step = "calculator"; st.rerun()
    with c2:
        if st.button("Finish"):
            st.session_state.step = "intro"; st.rerun()