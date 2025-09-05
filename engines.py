# engines.py
# Combined Decision Support Engines (Planner + Calculator)
# Safe, deterministic scoring + defensive JSON loading.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional
import json


# ----------------------------- Utilities ----------------------------- #

def _load_json(path: Optional[str | Path]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        p = Path(path)
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


# --------------------------- Planner Engine -------------------------- #

@dataclass
class PlannerResult:
    care_type: str                   # "in_home" | "assisted_living" | "memory_care"
    scores: Dict[str, int]           # raw category scores
    flags: Set[str]                  # gating/safety flags
    reasons: List[str]               # human-readable bullets
    advisory: Optional[str] = None   # optional blurb


class PlannerEngine:
    """
    Loads Q/A and recommendation config JSONs and produces a deterministic
    recommendation via `run(answers)`.
    """

    def __init__(self, qa_path: Optional[str | Path] = None, rec_path: Optional[str | Path] = None):
        self.qa: Dict[str, Any] = _load_json(qa_path)
        self.rec: Dict[str, Any] = _load_json(rec_path)

        # Optional weights/thresholds from JSON
        self.weights: Dict[str, int] = (self.rec.get("weights") or {})

        raw_final = self.rec.get("final_thresholds") or {}
        self.final_thresholds = {
            "in_home":         _as_int(raw_final.get("in_home", 5), 5),
            "assisted_living": _as_int(raw_final.get("assisted_living", 6), 6),
            "memory_care":     _as_int(raw_final.get("memory_care", 7), 7),
        }

        # Policy: explicit so random JSON fields can't break gates
        self.policy = {
            # Preference to stay home is a nudge, never a hard override
            "home_pref_is_soft_nudge": True,
            # These flags disqualify in-home regardless of score
            "require_24x7_supervision_block_inhome": True,
            "adl_dependency_blocks_inhome": True,
        }

    # ---------- Private scoring helpers ---------- #

    def _score_and_flags(
        self, answers: Dict[str, int]
    ) -> Tuple[Dict[str, int], Set[str], List[str]]:
        """
        Convert answers into category scores + safety flags + human reasons.
        Structures expected (all optional; engine is defensive):
          rec['per_question_weights']['q#']['choice'] -> {category: weight}
          rec['safety_flags']['q#']['choice'] -> [flag, ...]
          rec['reasons']['q#']['choice'] -> "bullet text"
        """
        scores = {"in_home": 0, "assisted_living": 0, "memory_care": 0}
        flags: Set[str] = set()
        reasons: List[str] = []

        questions = (self.qa or {}).get("questions", [])
        for idx, _q in enumerate(questions, start=1):
            key = f"q{idx}"
            choice = answers.get(key)
            if choice is None:
                continue

            # Weights
            pqw = (self.rec.get("per_question_weights") or {}).get(key) or {}
            w_for_choice = pqw.get(str(choice)) or {}
            for cat, w in w_for_choice.items():
                if cat in scores:
                    scores[cat] += _as_int(w, 0)

            # Flags
            sflags_map = (self.rec.get("safety_flags") or {}).get(key) or {}
            for fl in sflags_map.get(str(choice), []):
                if isinstance(fl, str) and fl:
                    flags.add(fl)

            # Reasons bullets
            rmap = (self.rec.get("reasons") or {}).get(key) or {}
            rtxt = rmap.get(str(choice))
            if rtxt:
                reasons.append(str(rtxt))

        return scores, flags, reasons

    def _apply_policy_gates(self, scores: Dict[str, int], flags: Set[str]) -> Dict[str, bool]:
        """
        Compute category eligibility after safety gates.
        """
        eligible = {"in_home": True, "assisted_living": True, "memory_care": True}

        # ADL dependency / non-ambulatory with total assist blocks in-home
        if self.policy["adl_dependency_blocks_inhome"] and (
            "needs_substantial_adl_help" in flags
            or "non_ambulatory_total_assist" in flags
        ):
            eligible["in_home"] = False

        # 24x7 supervision / wandering / unsafe alone blocks in-home
        if self.policy["require_24x7_supervision_block_inhome"] and (
            "needs_24x7_supervision" in flags
            or "wandering_risk" in flags
            or "unsafe_alone" in flags
        ):
            eligible["in_home"] = False

        return eligible

    def _decide(
        self,
        scores: Dict[str, int],
        flags: Set[str],
        answers: Dict[str, int],
    ) -> Tuple[str, List[str], Optional[str]]:
        """
        Final recommendation with gating, thresholds, and soft preference.
        """
        reasons: List[str] = []
        advisory: Optional[str] = None

        # Memory-care hard indications (locked unit, progressive impairment)
        if "needs_locked_unit" in flags or "progressive_cognitive_impairment" in flags:
            return "memory_care", reasons, advisory

        eligible = self._apply_policy_gates(scores, flags)

        # Preference nudge toward in-home (soft)
        pref_q = (self.rec.get("preference_question") or "q9")
        pref_map = (self.rec.get("preference_nudges") or {})  # e.g. {'1': -1, '2': 0, '3': +2}
        preferred = answers.get(pref_q)
        if self.policy["home_pref_is_soft_nudge"] and preferred is not None and eligible.get("in_home", False):
            nudge = _as_int(pref_map.get(str(preferred), 0), 0)
            if nudge:
                scores["in_home"] += nudge
                if nudge > 0:
                    reasons.append("Expressed preference to remain at home.")

        # Threshold floors
        floors = self.final_thresholds
        for cat in ("in_home", "assisted_living", "memory_care"):
            if scores.get(cat, 0) < floors.get(cat, 0):
                eligible[cat] = False

        # If everything is ineligible, fall back to assisted living for safety
        candidates = [(c, scores.get(c, 0)) for c, ok in eligible.items() if ok]
        if not candidates:
            return "assisted_living", reasons + ["Safety needs limit in-home feasibility."], advisory

        # Tie-break toward higher acuity when scores are equal
        acuity_rank = {"in_home": 0, "assisted_living": 1, "memory_care": 2}
        candidates.sort(key=lambda x: (x[1], acuity_rank[x[0]]), reverse=True)
        chosen = candidates[0][0]
        return chosen, reasons, advisory

    # ---------- Public API ---------- #

    def run(self, answers: Dict[str, int], conditional_answer: Optional[str] = None) -> PlannerResult:
        """
        Main entry: compute care_type, flags, scores, reasons, advisory.
        """
        scores, flags, reasons = self._score_and_flags(answers)

        # Optional conditional effects (e.g., if “Yes” to a follow-up)
        # Structure:
        # rec['conditional_effects']['1'] = {'add_flags': [...], 'scores': {'memory_care': 2}}
        if conditional_answer is not None:
            ce = (self.rec.get("conditional_effects") or {}).get(str(conditional_answer)) or {}
            for fl in (ce.get("add_flags") or []):
                if isinstance(fl, str) and fl:
                    flags.add(fl)
            for cat, inc in (ce.get("scores") or {}).items():
                if cat in scores:
                    scores[cat] += _as_int(inc, 0)

        care_type, more_reasons, advisory = self._decide(scores, flags, answers)
        reasons.extend(more_reasons)

        return PlannerResult(
            care_type=care_type,
            scores=scores,
            flags=flags,
            reasons=reasons,
            advisory=advisory,
        )


# -------------------------- Calculator Engine ------------------------ #

class CalculatorEngine:
    """
    Pragmatic cost model to keep the prototype consistent.
    It loads a main calculator JSON and an optional overlay JSON.
    Exposes .settings for app-level tweaks (VA, LTC, etc.).
    """

    def __init__(
        self,
        calc_path: Optional[str | Path] = None,
        overlay_path: Optional[str | Path] = None,
    ):
        # Try sensible defaults (the repo’s data files)
        default_calc = Path(__file__).resolve().parent / "data" / "senior_care_calculator_v5_full_with_instructions_ui.json"
        default_overlay = Path(__file__).resolve().parent / "data" / "senior_care_modular_overlay.json"

        self.config: Dict[str, Any] = _load_json(calc_path or default_calc)
        self.overlay: Dict[str, Any] = _load_json(overlay_path or default_overlay)

        # Public bag for the app to read/write
        self.settings: Dict[str, Any] = {
            # State/location multipliers
            "state_multipliers": self.config.get("state_multipliers", {
                "National": 1.00, "California": 1.25, "Washington": 1.20, "Texas": 0.95, "Florida": 1.05
            }),
            # Base costs (monthly) as conservative defaults; overridden if JSON has them
            "base_costs": self.config.get("base_costs", {
                "assisted_living": {"Low": 4200, "Medium": 5200, "High": 6200},
                "memory_care":     {"Low": 5200, "Medium": 6500, "High": 8000},
                # In-home is computed via hours*rate; provide baseline hourly if JSON missing
                "in_home_hourly": 32.0
            }),
            # Room modifiers for assisted/memory
            "room_mods": self.config.get("room_mods", {
                "Studio": 0.00, "1 Bedroom": 0.10, "Shared": -0.12
            }),
            # Mobility/chronic surcharges (percent)
            "mobility_mods": self.config.get("mobility_mods", {
                "Independent": 0.00, "Assisted": 0.05, "Non-ambulatory": 0.12
            }),
            "chronic_mods": self.config.get("chronic_mods", {
                "None": 0.00, "Some": 0.05, "Multiple/Complex": 0.12
            }),
            # VA & LTC knobs (the app overwrites these)
            "va_mapr_2025": self.config.get("va_mapr_2025", {
                "Veteran (no dependents) — A&A": 2358,
                "Veteran + 1 dependent — A&A": 2795,
                "Two veterans married, one A&A": 2795,
                "Surviving spouse — A&A": 1515,
                "Surviving spouse + 1 child — A&A": 1808,
            }),
            "ltc_monthly_add": _as_int(self.config.get("ltc_monthly_add", 1800), 1800),
            # In-home defaults
            "in_home_defaults": self.config.get("in_home_defaults", {
                "hours_per_day": 4, "days_per_month": 20
            }),
            # In-home hourly by state (optional)
            "in_home_hourly_by_state": self.config.get("in_home_hourly_by_state", {}),
        }

    # ---- public API ---- #

    def monthly_cost(self, inputs: Any) -> int:
        """
        Compute monthly cost for the given scenario.
        Expects 'inputs' to have (some of):
          - state
          - care_type: "in_home" | "assisted_living" | "memory_care"
          - care_level: "Low" | "Medium" | "High"
          - mobility: "Independent" | "Assisted" | "Non-ambulatory"
          - chronic: "None" | "Some" | "Multiple/Complex"
          - room_type (for facility care)
          - in_home_hours_per_day, in_home_days_per_month (for in-home)
        """
        state = getattr(inputs, "state", "National") or "National"
        care_type = (getattr(inputs, "care_type", None) or "in_home").strip()
        care_level = getattr(inputs, "care_level", "Medium") or "Medium"
        mobility = getattr(inputs, "mobility", "Independent") or "Independent"
        chronic = getattr(inputs, "chronic", "Some") or "Some"

        mult = float((self.settings.get("state_multipliers") or {}).get(state, 1.0))

        if care_type == "in_home":
            # Determine hourly rate
            hourly = self._in_home_hourly_for_state(state)
            hours = int(getattr(inputs, "in_home_hours_per_day", self.settings["in_home_defaults"]["hours_per_day"]))
            days = int(getattr(inputs, "in_home_days_per_month", self.settings["in_home_defaults"]["days_per_month"]))
            hours = max(0, min(hours, 24))
            days = max(0, min(days, 31))
            monthly = hourly * hours * days
            monthly *= mult
            # Mild adjustment for chronic/mobility to reflect higher skill mix
            monthly *= (1.0 + self._pct(self.settings["mobility_mods"].get(mobility, 0.0)))
            monthly *= (1.0 + self._pct(self.settings["chronic_mods"].get(chronic, 0.0)))
            return int(round(monthly))

        # Facility care
        base_costs = self.settings["base_costs"]
        base = float((base_costs.get(care_type) or {}).get(care_level, 0))
        if base <= 0:
            # Fallback based on care_type if missing
            base = 5200.0 if care_type == "assisted_living" else 7000.0

        base *= mult

        # Room modifiers
        room_type = getattr(inputs, "room_type", "Studio")
        base *= (1.0 + self._pct((self.settings.get("room_mods") or {}).get(room_type, 0.0)))

        # Mobility / chronic modifiers
        base *= (1.0 + self._pct(self.settings["mobility_mods"].get(mobility, 0.0)))
        base *= (1.0 + self._pct(self.settings["chronic_mods"].get(chronic, 0.0)))

        return int(round(base))

    # ---- helpers ---- #

    def _in_home_hourly_for_state(self, state: str) -> float:
        by_state = self.settings.get("in_home_hourly_by_state") or {}
        if state in by_state:
            return float(by_state[state])
        # Fallback to base if no state entry
        base = self.settings["base_costs"].get("in_home_hourly", 32.0)
        return float(base)

    @staticmethod
    def _pct(v: float | int) -> float:
        # v is already a fraction (e.g., 0.10) in our settings
        return float(v) if isinstance(v, (int, float)) else 0.0