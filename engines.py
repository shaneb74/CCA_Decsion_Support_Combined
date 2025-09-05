# engines.py — PlannerEngine and CalculatorEngine
# Robust to updated JSON; includes _intish parsing, mobility/home-preference carryover hooks.

from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass
from typing import Dict, Any, Tuple, List, Set


def _intish(x, fallback=0) -> int:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x)
    if isinstance(x, str):
        m = re.search(r"-?\d+", x)
        if m:
            try:
                return int(m.group(0))
            except Exception:
                pass
    return int(fallback)


@dataclass
class PlannerResult:
    care_type: str
    flags: Set[str]
    scores: Dict[str, int]
    reasons: List[str]
    advisory: str | None = None


class PlannerEngine:
    def __init__(self, qa_path: str, rec_path: str):
        self.qa = json.load(open(qa_path, "r"))
        self.rec = json.load(open(rec_path, "r"))

        # thresholds / overrides can move around; normalize
        self.final_thresholds = (
            self.rec.get("final_thresholds")
            or self.rec.get("finalThresholds")
            or self.rec.get("thresholds")
            or {}
        )
        self.overrides = self.rec.get("overrides", {})
        # fallback cuts with intish parse
        self.assisted_cut = _intish(self.final_thresholds.get("assisted_living", 6), 6)
        self.inhome_cut = _intish(self.final_thresholds.get("in_home", 0), 0)
        self.memory_requires = set(
            (self.overrides.get("memory_care", {}) or {}).get("requires_all_flags", [])
        )

    def _score(self, answers: Dict[str, int]) -> Tuple[Dict[str, int], Set[str], List[str]]:
        """Very lightweight scorer: sum categories by per-answer weights in QA json."""
        scores: Dict[str, int] = {}
        flags: Set[str] = set()
        reasons: List[str] = []

        qlist = self.qa.get("questions", [])
        for idx, q in enumerate(qlist, start=1):
            ans_key = str(answers.get(f"q{idx}", ""))
            amap = q.get("answers", {})
            if ans_key not in amap:
                continue

            # weights per category
            weights = (q.get("weights") or {}).get(ans_key) or {}
            for cat, w in weights.items():
                scores[cat] = scores.get(cat, 0) + _intish(w, 0)

            # flag mapping
            f = (q.get("flags") or {}).get(ans_key)
            if isinstance(f, list):
                flags.update(f)
            elif isinstance(f, str) and f:
                flags.add(f)

            # textual reason (optional in JSON)
            r = (q.get("reasons") or {}).get(ans_key)
            if r:
                reasons.append(str(r))

        return scores, flags, reasons

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, List[str], str | None]:
        """Final decision with override behavior and thresholds."""
        # Memory care override only if all required flags present
        if self.memory_requires and self.memory_requires.issubset(flags):
            return "memory_care", ["Cognitive/behavioral needs indicate Memory Care."], None

        # Otherwise choose assisted vs in-home via scores
        # Prefer assisted if category "assisted" meets or exceeds cut
        assisted_score = scores.get("assisted", 0)
        inhome_score = scores.get("in_home", 0)

        if assisted_score >= self.assisted_cut:
            return "assisted_living", ["Care intensity suggests Assisted Living."], None

        # If home preference flag exists, tilt toward in-home
        if "prefers_home" in flags or inhome_score >= self.inhome_cut:
            return "in_home", ["Expressed preference to remain at home."], None

        # default: assisted if slightly higher
        if assisted_score >= inhome_score:
            return "assisted_living", ["Care intensity higher than home supports."], None
        return "in_home", ["Home supports appear sufficient with help."], None

    def run(self, answers: Dict[str, int], conditional_answer: str | None = None) -> PlannerResult:
        scores, flags, reasons = self._score(answers)

        # basic conditional wiring: add a flag if conditional “Yes”
        if conditional_answer in ("1", 1, "yes", "Yes"):
            flags.add("conditional_yes")

        care_type, final_reasons, advisory = self._decide(flags, scores)
        reasons = reasons + final_reasons

        return PlannerResult(
            care_type=care_type,
            flags=flags,
            scores=scores,
            reasons=reasons,
            advisory=advisory,
        )


class CalculatorEngine:
    """
    Minimal but solid calculator:

    - In-home: hourly * hours/day * days/month with state hourly map
    - Assisted/Memory: base * room adj * care level adj * state factor
    - Simple mobility/chronic surcharges
    - Exposes .settings for VA wizard and any UI defaults
    """
    def __init__(self):
        self.settings: Dict[str, Any] = {}
        # national baselines (illustrative; replace with your JSON-driven logic if desired)
        self.state_factor = {
            "National": 1.00,
            "Washington": 1.18,
            "California": 1.22,
            "Texas": 0.95,
            "Florida": 0.98,
        }
        self.inhome_hourly = {
            "National": 32,
            "Washington": 38,
            "California": 40,
            "Texas": 28,
            "Florida": 30,
        }
        self.facility_base = {
            "assisted_living": 4800,   # base for Studio
            "memory_care":     6800,   # base for Studio
        }
        self.room_adj = {"Studio": 1.00, "1 Bedroom": 1.15, "Shared": 0.85}
        self.care_adj = {"Low": 0.95, "Medium": 1.00, "High": 1.15}

    def monthly_cost(self, inp) -> int:
        state = getattr(inp, "state", "National")
        factor = float(self.state_factor.get(state, 1.0))
        care_type = getattr(inp, "care_type", "in_home")

        if care_type == "in_home":
            hours = int(getattr(inp, "in_home_hours_per_day", 0))
            days = int(getattr(inp, "in_home_days_per_month", 0))
            hourly = int(self.inhome_hourly.get(state, self.inhome_hourly["National"]))
            total = hours * days * hourly
            # mild surcharges by mobility/chronic
            mobility = getattr(inp, "mobility", "Independent")
            chronic = getattr(inp, "chronic", "None")
            if mobility == "Assisted":
                total = int(total * 1.05)
            elif mobility == "Non-ambulatory":
                total = int(total * 1.12)
            if chronic == "Multiple/Complex":
                total = int(total * 1.08)
            return int(total)

        # facility
        room = getattr(inp, "room_type", "Studio")
        care_level = getattr(inp, "care_level", "Medium")
        base = int(self.facility_base.get(care_type, self.facility_base["assisted_living"]))
        total = base * self.room_adj.get(room, 1.0) * self.care_adj.get(care_level, 1.0) * factor

        # minor surcharges for mobility/chronic
        mobility = getattr(inp, "mobility", "Independent")
        chronic = getattr(inp, "chronic", "None")
        if mobility == "Non-ambulatory":
            total *= 1.05
        if chronic == "Multiple/Complex":
            total *= 1.07

        return int(round(total))