# engines.py — Best-fit recommendation selector (JSON-first) + real cost engine
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

# Load pricing config at module level
pricing = json.load(open('config/pricing_config.json', 'r'))  # Adjust path if needed

ENGINE_STRICT_JSON = os.environ.get("ENGINE_STRICT_JSON", "false").lower() in {"1","true","yes","on"}

SEVERITY_RANK = {"memory_care": 3, "assisted_living": 2, "in_home": 1, "none": 0}

@dataclass
class PlannerResult:
    care_type: str
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None

def resolve_narrative(template: str, ctx: Dict[str, Any]) -> str:
    safe = {k: ("" if v is None else v) for k, v in ctx.items()}
    try:
        return template.format(**safe)
    except Exception:
        return template

class PlannerEngine:
    """Reads Q&A JSON and Recommendation JSON (repo root) and returns PlannerResult."""
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {}) or {}
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))

        th = self.rec.get("final_decision_thresholds", {}) or {}
        self.in_home_min = self._num(th.get("in_home_min"), 3)
        self.al_min      = self._num(th.get("assisted_living_min"), 6)

        dep_cfg = self.rec.get("dependence_flag_logic", {}) or {}
        self.dep_min = self._num(dep_cfg.get("dependence_flags_min"), 2)
        self.dep_trigger_list: List[str] = dep_cfg.get(
            "trigger_if_flags",
            ["high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"]
        )

    def _num(self, v: Any, default: int) -> int:
        try:
            return int(v) if isinstance(v, str) and v.isdigit() else int(float(v)) if isinstance(v, str) else int(v)
        except Exception:
            return default

    def run(self, answers: Dict[str, int], name: str = "you") -> PlannerResult:
        flags: Set[str] = set()
        for q in self.qa.get("questions", []):
            ans = answers.get(q.get("id", ""), None) or answers.get(f"q{self.qa['questions'].index(q) + 1}", None)
            if ans is None:
                continue
            ans = str(ans)
            for cat, triggers in q.get("trigger", {}).items():
                for t in triggers:
                    if str(t.get("answer")) == ans:
                        flags.add(t.get("flag"))
        scores = {"in_home": 0, "assisted_living": 0}
        scoring = self.rec.get("scoring", {})
        for f in flags:
            cat = self.rec.get("flag_to_category_mapping", {}).get(f, None)
            if not cat:
                continue
            for care, val in scoring.get("in_home", {}).items():
                if cat == care:
                    scores["in_home"] += val
            for care, val in scoring.get("assisted_living", {}).items():
                if cat == care:
                    scores["assisted_living"] += val
        reasons = []
        for care, score in scores.items():
            if score > 0:
                reasons.append(f"{care}: {score} points")
        dep_count = sum(1 for f in self.dep_trigger_list if f in flags)
        if dep_count >= self.dep_min:
            return PlannerResult("assisted_living", list(flags), scores, reasons, "Dependence triggers assisted living.", "dependence_flag_logic")
        if "severe_cognitive_risk" in flags:
            return PlannerResult("memory_care", list(flags), scores, reasons, "Severe cognitive risk triggers memory care.", "memory_care_override")
        if scores["assisted_living"] >= self.al_min:
            return PlannerResult("assisted_living", list(flags), scores, reasons, "Assisted living threshold met.", "assisted_living_threshold")
        if scores["in_home"] >= self.in_home_min:
            return PlannerResult("in_home", list(flags), scores, reasons, "In-home threshold met.", "in_home_threshold")
        return PlannerResult("none", list(flags), scores, reasons, "No care needed.", "no_care_needed")

class CalculatorEngine:
    """Computes monthly costs from normalized inputs."""
    def monthly_cost(self, inputs: Any) -> int:
        ct = getattr(inputs, "care_type", "in_home")
        lf = float(getattr(inputs, "location_factor", 1.0))
        if ct == "assisted_living":
            base = pricing["assisted_living"]["base"]
            care_add = pricing["assisted_living"]["care_add"].get(getattr(inputs, "al_care_level", "Light"), 0)
            room_add = {
                "Studio": 0, "1 Bedroom": 800, "2 Bedroom": 1500, "Shared": -600
            }.get(getattr(inputs, "al_room_type", "Studio"), 0)
            mobility_add = {
                "None": 0, "Walker": 150, "Wheelchair": 350
            }.get(getattr(inputs, "al_mobility", "None"), 0)
            chronic_add = {
                "None": 0, "Diabetes": 200, "Parkinson's": 500, "Complex": 900
            }.get(getattr(inputs, "al_chronic", "None"), 0)
            return int(round((base + care_add + room_add + mobility_add + chronic_add) * lf))

        if ct == "in_home":
            rate = pricing["in_home"]["hourly"] * (1 + pricing["in_home"]["agency_fee_pct"])
            hpd  = int(getattr(inputs, "ih_hours_per_day", 4) or 4)
            dpm  = int(getattr(inputs, "ih_days_per_month", 20) or 20)
            mobility_mult = {"None": 1.0, "Walker": 1.05, "Wheelchair": 1.1}.get(getattr(inputs, "ih_mobility", "None"), 1.0)
            chronic_mult  = {"None": 1.0, "Diabetes": 1.05, "Parkinson's": 1.12, "Complex": 1.2}.get(getattr(inputs, "ih_chronic", "None"), 1.0)
            return int(round(rate * hpd * dpm * mobility_mult * chronic_mult))

        if ct == "memory_care":
            base = pricing["memory_care"]["base"]
            level_add = {"Standard": 0, "High Acuity": 1200}.get(getattr(inputs, "mc_level", "Standard"), 0)
            mobility_add = {"None": 0, "Walker": 150, "Wheelchair": 350}.get(getattr(inputs, "mc_mobility", "None"), 0)
            chronic_add  = {"None": 0, "Diabetes": 200, "Parkinson's": 600, "Complex": 1000}.get(getattr(inputs, "mc_chronic", "None"), 0)
            return int(round((base + level_add + mobility_add + chronic_add) * lf))

        # none:
        return 0

# Optional: quick local test
if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    qa = root / "question_answer_logic_FINAL_UPDATED.json"
    rc = root / "recommendation_logic_FINAL_MASTER_UPDATED.json"
    if qa.exists() and rc.exists():
        pe = PlannerEngine(str(qa), str(rc))
        ok = pe.run({"q1":1,"q2":1,"q3":1,"q4":1,"q5":1,"q6":1,"q7":1,"q8":1,"q9":1})
        print("no-flags ->", ok.care_type, ok.scores)
