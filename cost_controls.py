# cost_controls.py
# UI and calculators for AL / MC / In-Home scenario controls
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

import streamlit as st


# ---------- Load calculator JSON (use your existing files) ----------
ROOT = Path(__file__).resolve().parent
CALC_JSON = ROOT / "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_JSON = ROOT / "senior_care_modular_overlay.json"  # optional

def _safe_load_json(p: Path, fallback: dict) -> dict:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

_CALC = _safe_load_json(CALC_JSON, {
    "lookups": {
        "state_multipliers": {"National": 1.0},
        "room_type": {"Studio": 4000, "1BR": 5000, "Shared": 3500},
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

try:
    _OVERLAY = _safe_load_json(OVERLAY_JSON, {})
except Exception:
    _OVERLAY = {}

_STATE_MULT  = _CALC["lookups"]["state_multipliers"]
_ROOM_BASE   = _CALC["lookups"]["room_type"]
_CARE_ADD    = _CALC["lookups"]["care_level_adders"]
_MOB_ADD     = _CALC["lookups"]["mobility_adders"]
_CHRONIC_ADD = _CALC["lookups"]["chronic_adders"]
_INHOME_RATE = _CALC["lookups"]["in_home_care_matrix"]
_MC_MULT     = float(_CALC["settings"]["memory_care_multiplier"])
_DAYS_PER_MO = int(_CALC["settings"]["days_per_month"])


# ---------- Helpers ----------
def prefill_mobility_from_flags(flags: Set[str]) -> str:
    """Carryover from Guided Care Plan flags → default mobility."""
    f = set(flags or [])
    if "high_mobility_dependence" in f:
        return "High"
    if "moderate_mobility" in f:
        return "Medium"
    return "Low"

def get_state_multiplier(state_label: str | None) -> float:
    try:
        return float(_STATE_MULT.get(state_label or "National", 1.0))
    except Exception:
        return 1.0


# ---------- UI blocks for each scenario ----------
def _al_controls(person_key: str, person_name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"al_{person_key}_{k}"
    default_mob = prefill_mobility_from_flags(flags)

    room  = st.selectbox(f"Room type — {person_name}", list(_ROOM_BASE.keys()),
                         index=0, key=sk("room"))
    level = st.select_slider(f"Care level — {person_name}", options=list(_CARE_ADD.keys()),
                             value="Medium", key=sk("care"))
    mob   = st.select_slider(f"Mobility — {person_name}", options=list(_MOB_ADD["facility"].keys()),
                             value=default_mob, key=sk("mob"))
    chron = st.select_slider(f"Chronic conditions — {person_name}",
                             options=list(_CHRONIC_ADD.keys()), value="Some", key=sk("chron"))

    base  = int(_ROOM_BASE[room])
    add   = int(_CARE_ADD[level]) + int(_MOB_ADD["facility"][mob]) + int(_CHRONIC_ADD[chron])
    monthly = int(round((base + add) * state_mult))
    return monthly


def _mc_controls(person_key: str, person_name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"mc_{person_key}_{k}"
    default_mob = prefill_mobility_from_flags(flags)

    room  = st.selectbox(f"Room type — {person_name}", list(_ROOM_BASE.keys()),
                         index=0, key=sk("room"))
    level = st.select_slider(f"Care level — {person_name}", options=list(_CARE_ADD.keys()),
                             value="Medium", key=sk("care"))
    mob   = st.select_slider(f"Mobility — {person_name}", options=list(_MOB_ADD["facility"].keys()),
                             value=default_mob, key=sk("mob"))
    chron = st.select_slider(f"Chronic conditions — {person_name}",
                             options=list(_CHRONIC_ADD.keys()), value="Multiple/Complex", key=sk("chron"))

    base = int(round(int(_ROOM_BASE[room]) * _MC_MULT))
    add  = int(_CARE_ADD[level]) + int(_MOB_ADD["facility"][mob]) + int(_CHRONIC_ADD[chron])
    monthly = int(round((base + add) * state_mult))
    return monthly


def _ih_controls(person_key: str, person_name: str, *, state_mult: float, flags: Set[str]) -> int:
    sk = lambda k: f"ih_{person_key}_{k}"
    default_mob = prefill_mobility_from_flags(flags)

    hours = st.slider(f"Hours per day — {person_name}", min_value=0, max_value=24,
                      step=2, value=8, key=sk("hours"))
    days  = st.slider(f"Days per month — {person_name}", min_value=0, max_value=_DAYS_PER_MO,
                      step=1, value=22, key=sk("days"))
    mob   = st.select_slider(f"Mobility — {person_name}", options=list(_MOB_ADD["in_home"].keys()),
                             value=default_mob, key=sk("mob"))
    chron = st.select_slider(f"Chronic conditions — {person_name}",
                             options=list(_CHRONIC_ADD.keys()), value="Some", key=sk("chron"))

    # Hourly rate depends on hours/day (matrix keys are strings)
    # fall back to the highest defined if missing
    if str(hours) in _INHOME_RATE:
        rate = float(_INHOME_RATE[str(hours)])
    else:
        # get the biggest key numerically
        max_key = max(_INHOME_RATE.keys(), key=lambda k: int(k))
        rate = float(_INHOME_RATE[max_key])

    labor = int(round(rate * hours * days))
    add   = int(_MOB_ADD["in_home"][mob]) + int(_CHRONIC_ADD[chron])
    monthly = int(round((labor + add) * state_mult))
    return monthly


def render_costs_for_active_recommendations() -> int:
    """
    Draw the Cost Planner section for the currently recommended scenarios.
    Uses session_state.people and session_state.planner_results (already working in your app).
    Returns the combined monthly total.
    """
    # --- Location (state multiplier) ---
    state_label = st.selectbox("Location", list(_STATE_MULT.keys()),
                               index=list(_STATE_MULT.keys()).index("National") if "National" in _STATE_MULT else 0,
                               key="cost_state")
    state_mult  = get_state_multiplier(state_label)

    combined = 0
    people  = st.session_state.get("people", [])
    results = st.session_state.get("planner_results", {})

    for i, person in enumerate(people):
        pid   = person.get("id", f"P{i+1}")           # "A" / "B"
        name  = person.get("display_name", f"Person {i+1}")
        rec   = results.get(pid, {})
        scen  = (rec.get("care_type") or "none").strip()
        flags = set(rec.get("flags", []))

        st.subheader(f"{name} — Scenario: {scen.replace('_',' ').title()}")

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
        combined += monthly

    st.subheader("Combined Total")
    st.caption("Estimated Combined Monthly Cost")
    st.markdown(f"### ${combined:,.0f}")

    return combined