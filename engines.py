
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class PlannerResult:
    care_type: str
    flags: Set[str] = field(default_factory=set)
    scores: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    advisory: Optional[str] = None


class PlannerEngine:
    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = Path(qa_path)
        self.rec_path = Path(rec_path)
        with open(self.qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(self.rec_path, "r", encoding="utf-8") as f:
            self.rec_logic_full = json.load(f)
        self.rec_logic = self.rec_logic_full.get("recommendations", self.rec_logic_full)

    def _safe_format(self, template: str, ctx: dict) -> str:
        class _D(dict):
            def __missing__(self, k): return "{" + k + "}"
        return (template or "").format_map(_D(ctx or {}))

    def _render_message(self, care_type: str, ctx: dict) -> Optional[str]:
        node = self.rec_logic.get(care_type, {})
        tpl = node.get("message_template") or node.get("helper_text") or node.get("message")
        if not tpl:
            return None
        return self._safe_format(tpl, ctx)

    def run(self, answers: Dict[str, int], conditional_answer: Optional[str] = None) -> PlannerResult:
        # Score and flags evaluation based on QA config
        weights = self.qa.get("weights", {})
        flags_cfg = self.qa.get("flags", {})

        scores: Dict[str, int] = {}
        flags: Set[str] = set()
        reasons: List[str] = []

        # Sum weights by category
        total_score = 0
        for qkey, val in answers.items():
            wmap = weights.get(qkey, {})
            pts = int(wmap.get(str(val), 0))
            scores[qkey] = pts
            total_score += pts

        # Flags
        for fname, fcfg in flags_cfg.items():
            qk = fcfg.get("question")
            trigger_vals = [int(v) for v in fcfg.get("values", [])]
            if qk and int(answers.get(qk, 0)) in trigger_vals:
                flags.add(fname)
                blurb = fcfg.get("reason")
                if blurb:
                    reasons.append(blurb)

        # Conditional input can add flags
        if conditional_answer is not None:
            cond_cfg = self.qa.get("conditional_questions", [])
            if cond_cfg:
                c0 = cond_cfg[0]
                if str(conditional_answer) in c0.get("flag_values", []):
                    flags.add(c0.get("flag_name", "conditional_triggered"))

        # Decision thresholds from rec logic
        cutoffs = self.rec_logic_full.get("cutoffs", {
            "assisted_living_min": 6,
            "memory_care_min": 10
        })
        al_cut = int(cutoffs.get("assisted_living_min", 6))
        mc_cut = int(cutoffs.get("memory_care_min", 10))

        # No-care path: all scores zero and no flags
        if total_score == 0 and len(flags) == 0:
            care_type = "no_care_needed"
        else:
            # Base decision by thresholds and flags
            if "severe_cognitive_decline" in flags or total_score >= mc_cut:
                care_type = "memory_care"
            elif total_score >= al_cut or "high_physical_assist" in flags:
                care_type = "assisted_living"
            else:
                care_type = "in_home"

        # Render advisory from templates if present
        ctx = {
            "name": "",  # UI can inject name if needed; we keep generic
            "greeting": "Good news," if care_type in ("in_home", "no_care_needed") else "Based on the answers,",
            "positive_state": "doing well",
            "encouragement": "Keep what’s working and re-check as needs change",
            "preference_clause": ""
        }
        advisory = self._render_message(care_type, ctx)

        return PlannerResult(
            care_type=care_type,
            flags=flags,
            scores=scores,
            reasons=reasons,
            advisory=advisory
        )


class CalculatorEngine:
    def __init__(self):
        # basic settings; can be extended by JSON overlays if you load them here
        self.settings = {
            "state_multiplier": {
                "National": 1.00, "Washington": 1.18, "California": 1.22, "Texas": 0.95, "Florida": 0.98
            },
            "base_rates": {  # baseline monthly for facility by room type
                "assisted_living": {"Studio": 4300, "1 Bedroom": 5200, "Shared": 3500},
                "memory_care": {"Studio": 5600, "1 Bedroom": 6500, "Shared": 4800},
            },
            "care_level_add": {"Low": 0.00, "Medium": 0.10, "High": 0.22},
            "mobility_add": {"Independent": 0.00, "Assisted": 0.05, "Non-ambulatory": 0.12},
            "chronic_add": {"None": 0.00, "Some": 0.05, "Multiple/Complex": 0.12},
            "in_home_hourly": 34,  # national average
            "memory_care_multiplier": 1.10,  # additional intensity on top of base
        }

    def monthly_cost(self, inp: Any) -> int:
        care_type = getattr(inp, "care_type", "in_home")
        state = getattr(inp, "state", "National")
        mult = float(self.settings["state_multiplier"].get(state, 1.0))

        if care_type in ("assisted_living", "memory_care"):
            room = getattr(inp, "room_type", "Studio")
            base_table = self.settings["base_rates"]["assisted_living"] if care_type == "assisted_living" else self.settings["base_rates"]["memory_care"]
            base = float(base_table.get(room, list(base_table.values())[0]))
            care_add = self.settings["care_level_add"].get(getattr(inp, "care_level", "Medium"), 0.10)
            mob_add = self.settings["mobility_add"].get(getattr(inp, "mobility", "Independent"), 0.00)
            chr_add = self.settings["chronic_add"].get(getattr(inp, "chronic", "Some"), 0.05)
            total = base * (1 + care_add + mob_add + chr_add)
            if care_type == "memory_care":
                total *= float(self.settings.get("memory_care_multiplier", 1.10))
            return int(round(total * mult))

        # In-home
        hourly = float(self.settings["in_home_hourly"])
        hpd = int(getattr(inp, "in_home_hours_per_day", 4))
        dpm = int(getattr(inp, "in_home_days_per_month", 20))
        raw = hourly * hpd * dpm
        care_add = self.settings["care_level_add"].get(getattr(inp, "care_level", "Medium"), 0.10)
        mob_add = self.settings["mobility_add"].get(getattr(inp, "mobility", "Independent"), 0.00)
        chr_add = self.settings["chronic_add"].get(getattr(inp, "chronic", "Some"), 0.05)
        total = raw * (1 + care_add + mob_add + chr_add)
        return int(round(total * mult))

    # Legacy compatibility if someone's calling estimate(care_type)
    def estimate(self, care_type: str) -> int:
        dummy = type("X", (), {})()
        dummy.care_type = care_type
        dummy.state = "National"
        dummy.care_level = "Medium"
        dummy.mobility = "Independent"
        dummy.chronic = "Some"
        if care_type in ("assisted_living", "memory_care"):
            dummy.room_type = "Studio"
        else:
            dummy.in_home_hours_per_day = 4
            dummy.in_home_days_per_month = 20
        return self.monthly_cost(dummy)
