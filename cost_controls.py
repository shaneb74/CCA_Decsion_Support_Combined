# cost_controls.py
# UI + calculators for scenario costs (In-home, Assisted Living, Memory Care)
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

import streamlit as st


ROOT = Path(__file__).resolve().parent
CALC_JSON   = ROOT / "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_JSON = ROOT / "senior_care_modular_overlay.json"  # optional


def _safe_load_json(p: Path, fallback: dict) -> dict:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


# ---- Load calculator config ----
_CALC = _safe_load_json(CALC_JSON, {
    "lookups": {
        "state_multipliers": {"National": 1.0},
        "room_type": {"Studio": 4000, "1 Bedroom": 5000, "Shared": 3500},
        "care_level_adders": {"Low": 300, "Medium": 800, "High": 1500},
        "mobility_adders": {
            "facility": {"Low": 0, "Medium": 250, "High": 500},
            "in_home": {"Low": 0, "Medium": 150, "High": 300},
        },
        "chronic_adders": {"None": 0, "Some": 200, "Multiple/Complex": 600},
        "in_home_care_matrix": {"0": 0, "4": 38, "6": 35, "8": 32, "10": 30, "12": 28, "16": 27, "24": 25},
    },
    "settings": {
        "memory_care_multiplier": 1.25,
        "days_per_month": 30,
    },
})
_OVERLAY = _safe_load_json(OVERLAY_JSON, {})

_STATE_MULT  = _CALC["lookups"]["state_multipliers"]
_ROOM_BASE   = _CALC["lookups"]["room_type"]
_CARE_ADD    = _CALC["lookups"]["care_level_adders"]
_MOB_ADD     = _CALC["lookups"]["mobility_adders"]
_CHRONIC_ADD = _CALC["lookups"]["chronic_adders"]
_INHOME_RATE = _CALC["lookups"]["in_home_care_matrix"]
_MC_MULT     = float(_CALC["settings"]["memory_care_multiplier"])
_DAYS_PER_MO = int(_CALC["settings"]["days_per_month"])


# ---------- Location control (call exactly once in app.py) ----------
def render_location_control():
    """Single shared Location dropdown. Stores selection in st.session_state.cost_state."""
    if "cost_state" not in st.session_state:
        st.session_state.cost_state = "National"
    options = list(_STATE_MULT.keys())
    idx = options.index(st.session_state.cost_state) if st.session_state.cost_state in options else 0
    choice = st.selectbox("Location", options, index=idx, key="cost_state")
    st.session_state.cost_state = choice  # keep persistent
    return choice


def _get_state_multiplier() -> float:
    label = st.session_state.get("cost_state", "National")
    try:
        return float(_STATE_MULT.get(label, 1.0))
    except Exception:
        return 1.0


# ---------- Flag carryover ----------
def prefill_mobility_from_flags(flags: Set[str]) -> str:
    f = set(flags or [])
    if "high_mobility_dependence" in f:
        return "High"
    if "moderate_mobility" in f:
        return "Medium"
    return "Low"


# ---------- Robust result extractor ----------
def _extract_result(rec: Any) -> Dict[str, Any]:
    if rec is None:
        return {"care_type": "none", "flags": []}
    if isinstance(rec, dict):
        return {"care_type": rec.get("care_type", "none"), "flags": list(rec.get("flags", []))}
    return {"care_type": getattr(rec, "care_type", "none"), "flags": list(getattr(rec, "flags", []) or [])}


# ---------- Scenario controls ----------
def _al_controls(pid: str, name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"al_{pid}_{k}"
    default_mob = prefill_mobility_from_flags(flags)

    room  = st.selectbox(f"Room type — {name}", list(_ROOM_BASE.keys()),
                         index=0, key=sk("room"))
    level = st.selectbox(f"Care level — {name}", list(_CARE_ADD.keys()),
                         index=list(_CARE_ADD.keys()).index("Medium"), key=sk("care"))
    mob   = st.selectbox(f"Mobility — {name}", list(_MOB_ADD["facility"].keys()),
                         index=list(_MOB_ADD["facility"].keys()).index(default_mob), key=sk("mob"))
    chron = st.selectbox(f"Chronic conditions — {name}", list(_CHRONIC_ADD.keys()),
                         index=list(_CHRONIC_ADD.keys()).index("Some"), key=sk("chron"))

    base = int(_ROOM_BASE[room])
    add  = int(_CARE_ADD[level]) + int(_MOB_ADD["facility"][mob]) + int(_CHRONIC_ADD[chron])
    monthly = int(round((base + add) * state_mult))
    return monthly


def _mc_controls(pid: str, name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"mc_{pid}_{k}"
    default_mob = prefill_mobility_from_flags(flags)

    room  = st.selectbox(f"Room type — {name}", list(_ROOM_BASE.keys()),
                         index=0, key=sk("room"))
    level = st.selectbox(f"Care level — {name}", list(_CARE_ADD.keys()),
                         index=list(_CARE_ADD.keys()).index("Medium"), key=sk("care"))
    mob   = st.selectbox(f"Mobility — {name}", list(_MOB_ADD["facility"].keys()),
                         index=list(_MOB_ADD["facility"].keys()).index(default_mob), key=sk("mob"))
    chron = st.selectbox(f"Chronic conditions — {name}", list(_CHRONIC_ADD.keys()),
                         index=list(_CHRONIC_ADD.keys()).index("Multiple/Complex"), key=sk("chron"))

    base = int(round(int(_ROOM_BASE[room]) * _MC_MULT))
    add  = int(_CARE_ADD[level]) + int(_MOB_ADD["facility"][mob]) + int(_CHRONIC_ADD[chron])
    monthly = int(round((base + add) * state_mult))
    return monthly


def _ih_controls(pid: str, name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"ih_{pid}_{k}"
    # Defaults: 4 hrs/day, 20 days/month per your spec
    hours = st.slider(f"Hours per day — {name}", 0, 24, 4, 1, key=sk("hours"))
    days  = st.slider(f"Days per month — {name}", 0, _DAYS_PER_MO, 20, 1, key=sk("days"))

    # Rate from matrix (keys are strings)
    rate = None
    if str(hours) in _INHOME_RATE:
        rate = float(_INHOME_RATE[str(hours)])
    else:
        # Find closest lower key if exact not present
        keys_int = sorted(int(k) for k in _INHOME_RATE.keys())
        lower = max((k for k in keys_int if k <= hours), default=keys_int[0])
        rate = float(_INHOME_RATE[str(lower)])

    labor = int(round(rate * hours * days))
    monthly = int(round(labor * state_mult))
    return monthly


# ---------- Public: render costs for the currently active recommendations ----------
def render_costs_for_active_recommendations() -> int:
    """
    Renders:
      - One Location dropdown (assumes app called render_location_control() already)
      - For each person: scenario selector + relevant controls
      - Per-person subtotal + Combined total

    Returns combined monthly cost (int).
    """
    state_mult = _get_state_multiplier()

    combined = 0
    people  = st.session_state.get("people", [])
    results = st.session_state.get("planner_results", {})

    for i, person in enumerate(people):
        pid   = person.get("id", f"P{i+1}")
        name  = person.get("display_name", f"Person {i+1}")
        raw   = results.get(pid)
        rec   = _extract_result(raw)
        rec_care = (rec.get("care_type") or "none").strip().lower()
        flags = set(rec.get("flags", []))

        # ---- scenario override (user can choose different scenario) ----
        override_key = f"scenario_override_{pid}"
        scenario_options = {
            "in_home": "In-home Care",
            "assisted_living": "Assisted Living",
            "memory_care": "Memory Care",
            "none": "No plan needed",
        }
        reverse_map = {v: k for k, v in scenario_options.items()}
        default_label = scenario_options.get(rec_care, "No plan needed")

        st.subheader(f"{name} — Scenario: {default_label}")
        chosen_label = st.selectbox(
            f"Care scenario for {name}",
            list(scenario_options.values()),
            index=list(scenario_options.values()).index(default_label),
            key=override_key,
            help="You can price a different option without redoing questions.",
        )
        scen = reverse_map[chosen_label]

        # ---- scenario-specific controls ----
        if scen == "assisted_living":
            monthly = _al_controls(pid, name, state_mult=state_mult, flags=flags)
        elif scen == "memory_care":
            monthly = _mc_controls(pid, name, state_mult=state_mult, flags=flags)
        elif scen == "in_home":
            monthly = _ih_controls(pid, name, state_mult=state_mult, flags=flags)
        else:
            st.caption("No plan needed.")
            monthly = 0

        st.caption("Estimated Monthly Cost")
        st.markdown(f"### ${monthly:,.0f}")
        st.markdown("---")

        # Store per-person result in case other pages need it
        st.session_state.setdefault("cost_estimates", {})
        st.session_state["cost_estimates"][pid] = {"scenario": scen, "monthly": monthly}

        combined += monthly

    st.subheader("Combined Total")
    st.caption("Estimated Combined Monthly Cost")
    st.markdown(f"### ${combined:,.0f}")

    return combined