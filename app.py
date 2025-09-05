
from pathlib import Path
from types import SimpleNamespace
import traceback
import streamlit as st

# ----- Page config -----
st.set_page_config(page_title="Senior Navigator • Planner + Cost", page_icon="🧭", layout="centered")


# ---------- Safe answer-map helpers (prevents KeyError on non-1..N keys) ----------
def order_answer_map(amap):
    """Return (ordered_keys, ordered_labels) safely whether keys are '1','2',... or arbitrary strings.
    - If all keys are int-like, sort numerically.
    - Else, sort by key as str for stability.
    """
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
    """Render a radio from a JSON answer map and return the *selected key* (string).
    Falls back to default_key (if provided) or the first ordered option.
    """
    ordered_keys, ordered_labels = order_answer_map(amap)
    if not ordered_labels:
        return default_key
    if default_key is not None and str(default_key) in ordered_keys:
        idx = ordered_keys.index(str(default_key))
    else:
        idx = 0
    sel_label = st.radio(label, options=ordered_labels, index=idx, key=key, help=help_text)
    return ordered_keys[ordered_labels.index(sel_label)]


# ----- Paths: all files in repo root -----
ROOT = Path(__file__).resolve().parent
QA_PATH = ROOT / "question_answer_logic_FINAL_UPDATED.json"
REC_PATH = ROOT / "recommendation_logic_FINAL_MASTER_UPDATED.json"

# ----- Engines -----
try:
    from engines import PlannerEngine, CalculatorEngine
except Exception:
    st.error("Failed to import engines.py")
    st.code(traceback.format_exc())
    st.stop()

missing = [p for p in (QA_PATH, REC_PATH) if not p.exists()]
if missing:
    st.error("Missing required JSON files:\n" + "\n".join(f"• {m}" for m in missing))
    st.stop()

try:
    planner = PlannerEngine(str(QA_PATH), str(REC_PATH))
except Exception:
    st.error("PlannerEngine() failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

try:
    calculator = CalculatorEngine()
except Exception:
    st.error("CalculatorEngine() failed to initialize.")
    st.code(traceback.format_exc())
    st.stop()

# ----- Helpers -----
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


# ----- Session init -----
if "step" not in st.session_state:
    st.session_state.step = "intro"

st.sidebar.title("Senior Navigator")
st.sidebar.caption("Planner → Costs → Budget → Breakdown")
st.sidebar.button("Start over", on_click=reset_all)


# ===================== UI Flow =====================

# Intro
if st.session_state.step == "intro":
    st.title("Let’s take this one step at a time")
    st.markdown("""
Choosing senior living or in-home support can feel overwhelming.  
This tool breaks it into clear steps.

1. Answer quick care questions → we recommend a care type.  
2. Review costs for that scenario (you can switch it).  
3. Add income, benefits, and assets to see affordability.  
4. View a detailed breakdown you can save or revisit.
""")
    if st.button("Start"):
        st.session_state.step = "audience"
        st.rerun()

# Audience
elif st.session_state.step == "audience":
    st.header("Who is this plan for?")
    role = st.radio("Select one:", ["Myself", "My spouse/partner", "My parent", "Both parents", "Someone else"])
    people = []
    if role == "Both parents":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Parent 1 name", value="Mom", key="p1_name", placeholder="Name")
        with c2:
            n2 = st.text_input("Parent 2 name", value="Dad", key="p2_name", placeholder="Name")
        people = [{"id": "A", "display_name": n1, "relationship": "parent"},
                  {"id": "B", "display_name": n2, "relationship": "parent"}]
    else:
        default = "Alex" if role != "My parent" else "Mom"
        n = st.text_input("Name", value=default, key="p_name", placeholder="Name")
        map_rel = {"Myself": "self", "My spouse/partner": "spouse", "My parent": "parent", "Someone else": "other"}
        people = [{"id": "A", "display_name": n, "relationship": map_rel.get(role, "other")}]
    st.caption("Next, we’ll ask short care questions for each person.")
    if st.button("Continue"):
        st.session_state.people = people
        st.session_state.current_person = 0
        st.session_state.answers = {}
        st.session_state.results = {}
        st.session_state.step = "planner"
        st.rerun()

# Planner (simple list version; your current build may have one-by-one mobile view)
elif st.session_state.step == "planner":
    ppl = st.session_state.get("people", [])
    i = st.session_state.get("current_person", 0)
    if not ppl:
        reset_all(); st.rerun()
    person = ppl[i]
    name = person["display_name"]
    st.header(f"Care Plan Questions for {name}")
    qa = planner.qa or {}
    answers = st.session_state.answers.get(person["id"], {})

    # Render all questions (keeps your current desktop flow)
    for idx, q in enumerate(qa.get("questions", []), start=1):
        amap = q.get("answers", {})
        ordered = [amap[k] for k in sorted(map(int, amap.keys()))]
        prev = answers.get(f"q{idx}")
        idx_default = ordered.index(prev) if prev in ordered else 0
        sel = st.radio(q.get("question", f"Q{idx}"), options=ordered, index=idx_default, key=f"{person['id']}_q{idx}")
        answers[f"q{idx}"] = sel

    st.session_state.answers[person["id"]] = answers

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back"):
            if i == 0:
                st.session_state.step = "audience"
            else:
                st.session_state.current_person = i - 1
            st.rerun()
    with c2:
        if st.button("Next"):
            try:
                # Pass the person's name as contextual for rendering
                payload = {**answers, "_person_name": name}
                res = planner.run(payload, conditional_answer=None)
            except Exception:
                st.error("PlannerEngine.run failed.")
                st.code(traceback.format_exc())
                st.stop()

            # Normalize result regardless of object/dict
            if hasattr(res, "__dict__"):
                care_type = getattr(res, "care_type", None)
                flags = set(getattr(res, "flags", set()) or set())
                scores = getattr(res, "scores", {}) or {}
                reasons = list(getattr(res, "reasons", []) or [])
                narrative = (getattr(res, "advisory", None)
                             or getattr(res, "message", None)
                             or getattr(res, "message_rendered", None))
            else:
                care_type = res.get("care_type")
                flags = set(res.get("flags", []))
                scores = res.get("scores", {})
                reasons = list(res.get("reasons", []))
                narrative = (res.get("advisory")
                             or res.get("message")
                             or res.get("message_rendered"))

            st.session_state.results[person["id"]] = {
                "care_type": care_type,
                "flags": list(flags),
                "scores": scores,
                "reasons": reasons,
                "advisory": narrative,
            }
            if i + 1 < len(ppl):
                st.session_state.current_person = i + 1
                st.rerun()
            else:
                st.session_state.step = "recommendations"
                st.rerun()

# Recommendations
elif st.session_state.step == "recommendations":
    st.header("Our Recommendation")
    for p in st.session_state.get("people", []):
        rec = st.session_state.results.get(p["id"], {})
        care = (rec.get("care_type") or "in_home").replace("_", " ").title()
        st.subheader(f"{p['display_name']}: {care}")
        # Narrative
        narrative = (rec.get("advisory") or rec.get("message") or rec.get("message_rendered"))
        if narrative:
            st.info(narrative)
        # Reasons list (if any)
        for r in rec.get("reasons", []):
            st.write("• " + str(r))
        st.divider()

    if st.button("See Costs"):
        st.session_state.step = "calculator"
        st.rerun()

# Calculator (minimal)
elif st.session_state.step == "calculator":
    st.header("Cost Planner")
    total = 0
    for p in st.session_state.get("people", []):
        pid = p["id"]
        name = p["display_name"]
        rec = st.session_state.results.get(pid, {})
        care_type = rec.get("care_type", "in_home")
        st.subheader(f"{name} — Scenario: {care_type.replace('_', ' ').title()}")
        if care_type in ("assisted_living", "memory_care"):
            room = st.selectbox("Room Type", ["Studio", "1 Bedroom", "Shared"], key=f"{pid}_room")
            inp = make_inputs(care_type=care_type, room_type=room)
        else:
            hours = st.slider("In-home care hours per day", 0, 24, 4, 1, key=f"{pid}_hours")
            days = st.slider("Days of care per month", 0, 31, 20, 1, key=f"{pid}_days")
            inp = make_inputs(care_type=care_type, in_home_hours_per_day=hours, in_home_days_per_month=days)

        try:
            monthly = calculator.monthly_cost(inp)
        except Exception:
            st.error("CalculatorEngine failed while computing monthly cost.")
            st.code(traceback.format_exc())
            st.stop()
        st.metric("Estimated Monthly Cost", f"${int(monthly):,}")
        total += int(monthly)

    st.subheader("Combined Total")
    st.metric("Estimated Combined Monthly Cost", f"${int(total):,}")
    if st.button("Finish"):
        st.session_state.step = "intro"
        st.rerun()
