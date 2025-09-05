# engines.py — Combined engines with JSON-driven Planner and fixed In-Home math
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

# ---------------- Planner ----------------
class PlannerEngine:
    """
    JSON-driven planner:
    - Reads question/answer triggers from question_answer_logic JSON
    - Applies scoring weights from recommendation_logic JSON
    - Produces care_type and supportive flags/reasons
    Memory care is ONLY recommended when JSON flags require it, not for mobility alone.
    """
    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = Path(qa_path)
        self.rec_path = Path(rec_path)
        with self.qa_path.open("r", encoding="utf-8") as f:
            self.qa: Dict[str, Any] = json.load(f)
        with self.rec_path.open("r", encoding="utf-8") as f:
            self.rec: Dict[str, Any] = json.load(f)

        # Scoring weights
        scoring = self.rec.get("scoring", {})
        self.weights_in_home: Dict[str, int] = scoring.get("in_home", {})
        self.weights_assisted: Dict[str, int] = scoring.get("assisted_living", {})

        # Dependence logic
        dep_logic = self.rec.get("dependence_flag_logic", {}) or {}
        self.dep_trigger_list: List[str] = dep_logic.get("trigger_if_flags", []) or []
        self.dep_min_count: int = 2  # JSON text says "any 2 or more"

    def _collect_flags_and_categories(self, answers: Dict[str, int]) -> (Set[str], Set[str]):
        """
        Walk questions; accumulate flags and the 'categories' that fired (e.g., care_burden, home_safety).
        """
        flags: Set[str] = set()
        cats_hit: Set[str] = set()

        # Per-question triggers
        questions = self.qa.get("questions", []) or []
        for idx, q in enumerate(questions, start=1):
            a_key = f"q{idx}"
            if a_key not in answers:
                continue
            ans_val = int(answers[a_key])

            trig = q.get("trigger") or {}
            for category, rule_list in trig.items():
                for rule in rule_list:
                    if int(rule.get("answer", -999)) == ans_val:
                        flag = rule.get("flag")
                        if flag:
                            flags.add(flag)
                        cats_hit.add(category)

        # Conditional question flow handled in run()
        return flags, cats_hit

    def run(self, answers: Dict[str, int], conditional_answer: Optional[Union[str, int]] = None):
        # Parse base flags/categories
        flags, cats_hit = self._collect_flags_and_categories(answers)

        # Conditional: only active if prerequisite flag is present (e.g., severe cognitive decline)
        conds = self.qa.get("conditional_questions") or []
        if conds:
            cq = conds[0]
            prereq = cq.get("trigger")
            if (not prereq) or (prereq in flags):
                if conditional_answer is not None:
                    flag_map = cq.get("flag_on_answer") or {}
                    cand = flag_map.get(str(conditional_answer))
                    if cand:
                        flags.add(cand)

        # Scores: categories that fired push assisted-living; categories that didn't push in-home
        all_cats: Set[str] = set(self.weights_in_home.keys()) | set(self.weights_assisted.keys())
        assisted_score = sum(int(self.weights_assisted.get(cat, 0)) for cat in cats_hit)
        in_home_score = sum(int(self.weights_in_home.get(cat, 0)) for cat in (all_cats - cats_hit))

        # Dependence advisory if 2+ critical flags present
        critical_flags_present = sum(1 for f in self.dep_trigger_list if f in flags)
        if critical_flags_present >= self.dep_min_count:
            flags.add("high_overall_dependence")

        # Decide care_type per JSON rules
        care_type = "in_home"
        if "memory_care_required" in flags:
            care_type = "memory_care"
        else:
            if assisted_score >= 6:
                care_type = "assisted_living"
            elif in_home_score >= 6 and assisted_score < 6:
                care_type = "in_home"
            else:
                care_type = "assisted_living" if assisted_score >= 5 else "in_home"

        # Reasons/advisory text (succinct)
        reasons: List[str] = []
        if "severe_cognitive_decline" in flags:
            reasons.append("Cognitive responses indicate significant decline.")
        if "high_mobility_dependence" in flags:
            reasons.append("Mobility indicates wheelchair or near-immobility.")
        if "moderate_mobility" in flags:
            reasons.append("Mobility indicates regular assistance is needed.")
        if "high_safety_concern" in flags:
            reasons.append("Home safety risks are high and ongoing.")
        if "low_access" in flags or "very_low_access" in flags:
            reasons.append("Limited access to services and support nearby.")
        if "needs_financial_assistance" in flags:
            reasons.append("Budget constraints may limit in-home staffing or facility choice.")
        if "no_support" in flags:
            reasons.append("Limited caregiver support reported.")
        if "high_overall_dependence" in flags:
            reasons.append("Multiple high-dependence indicators present.")

        advisory = None
        if "memory_care_required" in flags:
            advisory = "Memory Care is recommended because 24/7 supervision is required and cannot be arranged at home."
        elif "severe_cognitive_decline" in flags:
            advisory = "Severe cognitive decline noted. Memory Care may be appropriate unless dependable 24/7 in-home support is available."

        return {
            "care_type": care_type,
            "flags": flags,
            "scores": {"assisted_living": assisted_score, "in_home": in_home_score},
            "reasons": reasons,
            "advisory": advisory,
        }

# ---------------- Calculator ----------------
@dataclass
class CalcInputs:
    state: str = "National"
    care_type: str = "in_home"  # in_home | assisted_living | memory_care
    care_level: str = "Medium"  # Low | Medium | High
    mobility: str = "Independent"  # Independent | Assisted | Non-ambulatory
    chronic: str = "Some"  # None | Some | Multiple/Complex
    # in-home only
    in_home_hours_per_day: int = 4
    in_home_days_per_month: int = 20
    # residence only
    room_type: str = "Studio"  # Studio | 1 Bedroom | Shared

class CalculatorEngine:
    """
    Cost calculator with explicit in-home math (hours/day × days/month × hourly),
    and simple multipliers for care level, mobility, chronic conditions, and state.
    """
    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings: Dict[str, Any] = dict(settings or {})

        # Base monthly for facility; hourly for in-home
        base = self.settings.get("base_rates", {})
        self.base: Dict[str, float] = {
            "assisted_living": float(base.get("assisted_living", 5200.0)),
            "memory_care": float(base.get("memory_care", 6500.0)),
            "in_home": float(base.get("in_home", 35.0)),  # hourly
        }

        self.room_mult: Dict[str, float] = self.settings.get("room_mult", {
            "Studio": 1.00,
            "1 Bedroom": 1.15,
            "Shared": 0.85,
        })

        self.state_adj: Dict[str, float] = self.settings.get("state_adj", {
            "National": 1.00,
            "Washington": 1.18,
            "California": 1.22,
            "Texas": 0.95,
            "Florida": 1.02,
        })

    def estimate(self, care_type: str) -> int:
        return self.monthly_cost(CalcInputs(care_type=care_type))

    def monthly_cost(self, inputs: Union[CalcInputs, Any]) -> int:
        care = getattr(inputs, "care_type", "in_home")
        state = getattr(inputs, "state", "National")
        care_level = getattr(inputs, "care_level", "Medium")
        mobility = getattr(inputs, "mobility", "Independent")
        chronic = getattr(inputs, "chronic", "Some")

        # Common multipliers
        level_mult = {"Low": 0.90, "Medium": 1.00, "High": 1.20}.get(care_level, 1.00)
        mob_mult = {"Independent": 1.00, "Assisted": 1.08, "Non-ambulatory": 1.15}.get(mobility, 1.00)
        chrn_mult = {"None": 0.95, "Some": 1.00, "Multiple/Complex": 1.15}.get(chronic, 1.00)
        state_mult = float(self.state_adj.get(state, 1.0))

        if care == "in_home":
            # hours/day × days/month × hourly
            hpd = int(getattr(inputs, "in_home_hours_per_day", 4) or 4)
            dpm = int(getattr(inputs, "in_home_days_per_month", 20) or 20)
            hourly = float(self.base.get("in_home", 35.0))
            hours_month = max(hpd, 0) * max(dpm, 0)
            est = hours_month * hourly
            total = est * level_mult * mob_mult * chrn_mult * state_mult
            return int(round(max(total, 0)))

        if care in ("assisted_living", "memory_care"):
            base = float(self.base.get(care, 5000.0))
            room = getattr(inputs, "room_type", "Studio")
            room_k = room if room in self.room_mult else "Studio"
            total = base * self.room_mult[room_k] * level_mult * mob_mult * chrn_mult * state_mult
            return int(round(max(total, 0)))

        # Fallback
        return int(round(max(float(self.base.get("assisted_living", 5200.0)) * state_mult, 0)))