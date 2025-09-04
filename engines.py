# engines.py — baseline engines with robust thresholds and a simple calculator
# Loads your JSONs, scores, and outputs care_type. Calculator provides a stable estimate().
# If your repo already has richer methods like monthly_cost(), app.py will call that instead.

import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any

# ---------- helpers ----------
def _to_int_threshold(val, default):
    """Accept int or descriptive string like 'Recommend if >= 6' and return the integer."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        m = re.search(r"\d+", val)
        if m:
            return int(m.group(0))
    return default

# ---------- planner ----------
@dataclass
class PlannerResult:
    care_type: str
    scores: Dict[str, int]
    flags: set
    reasons: list
    advisory: str | None = None

class PlannerEngine:
    def __init__(self, qa_path: str, rec_path: str):
        qa_p = Path(qa_path)
        rec_p = Path(rec_path)
        if not qa_p.exists() or not rec_p.exists():
            raise FileNotFoundError("QA or Recommendation JSON path missing.")
        with open(qa_p, "r") as f:
            self.qa = json.load(f)
        with open(rec_p, "r") as f:
            self.rec = json.load(f)
        self.final_thresholds = self.rec.get("final_thresholds", {})

    def _score(self, answers: Dict[str, int], conditional_answer: str | None):
        scores = {"in_home": 0, "assisted_living": 0, "memory_care": 0}
        flags = set()

        for q in self.qa.get("questions", []):
            qid = q.get("id")
            key = f"q{qid}"
            ans = answers.get(key)
            # accumulate scores if provided in QA JSON
            if ans is not None:
                s_map = q.get("scores", {})
                s_for_ans = s_map.get(str(ans)) or s_map.get(int(ans)) if isinstance(ans, int) else {}
                if s_for_ans:
                    for care, val in s_for_ans.items():
                        scores[care] = scores.get(care, 0) + int(val)
                # evaluate triggers for flags if present
                trig = q.get("trigger", {})
                for _, rule_list in trig.items():
                    for rule in rule_list:
                        if str(rule.get("answer")) == str(ans):
                            fl = rule.get("flag")
                            if fl:
                                flags.add(fl)

        if conditional_answer:
            cq_arr = self.qa.get("conditional_questions") or []
            if cq_arr:
                cq = cq_arr[0]
                s_map = cq.get("scores", {})
                s_for_ans = s_map.get(str(conditional_answer), {})
                for care, val in s_for_ans.items():
                    scores[care] = scores.get(care, 0) + int(val)

        return scores, flags

    def run(self, answers: Dict[str, int], conditional_answer: str | None = None) -> Dict[str, Any]:
        scores, flags = self._score(answers, conditional_answer)

        assisted_cut = _to_int_threshold(self.final_thresholds.get("assisted_living"), 6)
        memory_cut   = _to_int_threshold(self.final_thresholds.get("memory_care"), 7)
        inhome_cut   = _to_int_threshold(self.final_thresholds.get("in_home"), 5)

        # pick care_type using thresholds in typical priority order
        if scores.get("memory_care", 0) >= memory_cut:
            care_type = "memory_care"
        elif scores.get("assisted_living", 0) >= assisted_cut:
            care_type = "assisted_living"
        elif scores.get("in_home", 0) >= inhome_cut:
            care_type = "in_home"
        else:
            # fallback: highest score wins
            care_type = max(scores, key=scores.get)

        reasons = [f"{k.replace('_',' ').title()}: {v}" for k, v in scores.items()]
        advisory = None
        if "severe_cognitive_decline" in flags and care_type != "memory_care":
            advisory = "Significant supervision indicated. Consider memory care or increased supports."

        # Return a plain dict so app.py doesn’t care about dataclass import shape
        return {
            "care_type": care_type,
            "scores": scores,
            "flags": list(flags),
            "reasons": reasons,
            "advisory": advisory
        }

# ---------- calculator ----------
@dataclass
class CalcInputs:
    state: str = "National"
    care_type: str = "in_home"
    care_level: str = "Medium"
    mobility: str = "Independent"
    chronic: str = "Some"
    room_type: str | None = None
    in_home_hours_per_day: int | None = None
    in_home_days_per_month: int | None = None

class CalculatorEngine:
    """
    Stable baseline:
    - If your repo exposes a richer monthly_cost(inputs) method elsewhere, keep it.
    - This class provides monthly_cost() using simple heuristics so the app compiles.
    """
    def __init__(self):
        # Baseline market rates; replace with your JSON-driven settings if available
        self.base = {
            "in_home": 27,  # $/hour baseline
            "assisted_living": {
                "Studio": 4200, "1 Bedroom": 4800, "Shared": 3600
            },
            "memory_care": {
                "Studio": 5600, "1 Bedroom": 6200, "Shared": 4800
            }
        }
        self.state_adj = {
            "National": 1.00, "Washington": 1.18, "California": 1.22, "Texas": 0.95, "Florida": 1.00
        }
        self.level_adj = {"Low": 0.92, "Medium": 1.00, "High": 1.12}
        self.mob_adj = {"Independent": 0.98, "Assisted": 1.05, "Non-ambulatory": 1.12}
        self.chronic_adj = {"None": 0.96, "Some": 1.00, "Multiple/Complex": 1.10}

        # Expose settings stub so app.py can read from it safely if needed
        self.settings = {
            "ltc_monthly_add": 1800,
            "display_cap_years_funded": 30
        }

    def monthly_cost(self, inputs: CalcInputs | SimpleNamespace) -> int:
        state = getattr(inputs, "state", "National")
        care = getattr(inputs, "care_type", "in_home")
        level = getattr(inputs, "care_level", "Medium")
        mobility = getattr(inputs, "mobility", "Independent")
        chronic = getattr(inputs, "chronic", "Some")

        s_adj = self.state_adj.get(state, 1.0)
        lvl = self.level_adj.get(level, 1.0)
        mob = self.mob_adj.get(mobility, 1.0)
        chrn = self.chronic_adj.get(chronic, 1.0)

        if care == "in_home":
            # use both hours/day and days/month if provided
            hpd = int(getattr(inputs, "in_home_hours_per_day", 4) or 4)
            dpm = int(getattr(inputs, "in_home_days_per_month", 20) or 20)
            hours_month = max(hpd, 0) * max(dpm, 0)
            hourly = self.base["in_home"]
            est = hourly * hours_month
            est = int(round(est * s_adj * lvl * mob * chrn))
            return max(est, 0)

        # facility scenarios
        room = getattr(inputs, "room_type", None) or "Studio"
        base_map = self.base["assisted_living"] if care == "assisted_living" else self.base["memory_care"]
        base = base_map.get(room, list(base_map.values())[0])
        est = int(round(base * s_adj * lvl * mob * chrn))
        return max(est, 0)

    # minimal API used by earlier prototypes
    def estimate(self, care_type: str) -> int:
        if care_type == "in_home":
            return 27 * 4 * 20  # baseline 4 hrs/day, 20 days/month
        if care_type == "assisted_living":
            return self.base["assisted_living"]["Studio"]
        if care_type == "memory_care":
            return self.base["memory_care"]["Studio"]
        return 0