# engines.py — production: JSON-driven recommendations + cost calculator
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class PlannerResult:
    care_type: str
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None


class PlannerEngine:
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))

        th = self.rec.get("final_decision_thresholds", {})
        self.in_home_min = self._num(th.get("in_home_min"), 3)
        self.al_min      = self._num(th.get("assisted_living_min"), 6)
        self.dep_min     = self._num(th.get("dependence_flags_min"), 2)

        self.dependence_list = self.rec.get("dependence_flag_logic", {}).get(
            "trigger_if_flags",
            ["high_dependence", "high_mobility_dependence", "no_support",
             "severe_cognitive_risk", "high_safety_concern"]
        )

        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})

    @staticmethod
    def _num(v: Any, default: int) -> int:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m:
                return int(m.group(1))
        return default

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule_name, care_type = self._decide(flags, scores)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=care_type,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule_name,
        )

    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []

        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            triggers = q.get("trigger", {})
            for _category, tlist in triggers.items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            debug.append(f"{qk}={a} → flag {fl}")

        categories: Set[str] = set()
        for fl in flags:
            cat = self.flag_to_cat.get(fl)
            if cat:
                categories.add(cat)

        if categories:
            debug.append(f"categories: {sorted(categories)}")

        s_in = sum(self.rec["scoring"]["in_home"].get(c, 0) for c in categories)
        s_al = sum(self.rec["scoring"]["assisted_living"].get(c, 0) for c in categories)
        scores = {"in_home_score": int(s_in), "assisted_living_score": int(s_al)}
        debug.append(f"scores: in_home={s_in} al={s_al}")

        return flags, scores, debug

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        f = flags
        s = scores
        in_min = self.in_home_min
        al_min = self.al_min
        dep_min = self.dep_min

        def any_of(*need: str) -> bool:
            return any(n in f for n in need)

        def none_of(*ban: str) -> bool:
            return all(n not in f for n in ban)

        if "severe_cognitive_risk" in f and any_of("no_support", "high_safety_concern"):
            return "memory_care_override", "memory_care"

        for rule in self.precedence:
            meta = self.rules.get(rule, {})
            outcome = meta.get("outcome")

            if rule == "dependence_flag_logic":
                count = sum(1 for fl in self.dependence_list if fl in f)
                if count >= dep_min:
                    return rule, (outcome or "assisted_living")

            elif rule == "assisted_living_score":
                if s["assisted_living_score"] >= al_min:
                    return rule, (outcome or "assisted_living")

            elif rule == "balanced_al":
                if (s["assisted_living_score"] >= al_min and
                    s["in_home_score"] >= in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk")):
                    return rule, (outcome or "assisted_living")

            elif rule == "in_home_with_mobility_challenges":
                if (s["assisted_living_score"] >= al_min - 1 and
                    s["in_home_score"] >= in_min and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk")):
                    return rule, (outcome or "in_home")

            elif rule == "in_home_possible_with_cognitive_and_safety_risks":
                if (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] >= in_min and
                    any(n in f for n in ["moderate_cognitive_decline","severe_cognitive_risk","moderate_safety_concern","high_safety_concern"])):
                    return rule, (outcome or "in_home")

            elif rule == "in_home_with_support_and_financial_needs":
                if (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] < al_min and
                    "needs_financial_assistance" in f):
                    return rule, (outcome or "in_home")

            elif rule == "independent_with_safety_concern":
                if (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_dependence", "high_mobility_dependence") and
                    any(n in f for n in ["moderate_safety_concern","high_safety_concern"])):
                    return rule, (outcome or "in_home")

            elif rule == "independent_no_support_risk":
                if (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_mobility_dependence") and "no_support" in f):
                    return rule, (outcome or "in_home")

            elif rule == "no_care_needed":
                if (s["assisted_living_score"] < in_min and
                    s["in_home_score"] < in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "severe_cognitive_risk", "high_safety_concern",
                            "moderate_cognitive_decline", "moderate_safety_concern", "high_risk")):
                    return rule, "none"

            else:
                if outcome:
                    return rule, outcome

        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        return "no_care_needed", "none"

    def _rand(self, seq: List[str]) -> str:
        return random.choice(seq) if seq else ""

    def _render_message(self, template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            return template

    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            if flg in issue_catalog and issue_catalog[flg]:
                phrases.append(self._rand(issue_catalog[flg]))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        if "strongly_prefers_home" in flags:
            pref_key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            pref_key = "prefers_home"
        elif "open_to_move" in flags:
            pref_key = "open_to_move"
        else:
            pref_key = "default"
        preference_clause = self._rand(self.rec.get("preference_clause_templates", {}).get(pref_key, [""]))

        greeting       = self._rand(self.rec.get("greeting_templates", ["Hello"]))
        positive_state = self._rand(self.rec.get("positive_state_templates", ["doing well"]))
        encouragement  = self._rand(self.rec.get("encouragement_templates", ["We’re here for you."]))

        ctx = dict(
            name=name,
            key_issues=key_issues,
            preference_clause=preference_clause,
            greeting=greeting,
            positive_state=positive_state,
            encouragement=encouragement,
            home_preference=("prefer to stay home" if ("prefers_home" in flags or "strongly_prefers_home" in flags) else "are open to moving"),
            recommendation=(self.rules.get(rule_name, {}).get("outcome", "in_home").replace("_", " ").title()),
        )
        return self._render_message(template, ctx)


class CalculatorEngine:
    def __init__(self, *args, **kwargs):
        self.location_factor = {
            "National": 1.00,
            "Washington": 1.15,
            "California": 1.25,
            "Texas": 0.95,
            "Florida": 1.05,
        }

        self.base_assisted_living = 6500
        self.base_memory_care = 8500
        self.base_in_home_hourly = 30

        self.al_care_level_add = {"Low": 0, "Medium": 750, "High": 1500}
        self.al_room_add = {"Studio": 0, "1 Bedroom": 500, "2 Bedroom": 1200}
        self.mobility_add = {"Independent": 0, "Needs some help": 300, "Wheelchair/High assistance": 600}
        self.chronic_add = {"None": 0, "Some": 400, "Many/complex": 900}

        self.ih_complexity_mult = {
            ("Independent", "None"): 1.00,
            ("Independent", "Some"): 1.08,
            ("Independent", "Many/complex"): 1.15,
            ("Needs some help", "None"): 1.10,
            ("Needs some help", "Some"): 1.18,
            ("Needs some help", "Many/complex"): 1.27,
            ("Wheelchair/High assistance", "None"): 1.22,
            ("Wheelchair/High assistance", "Some"): 1.30,
            ("Wheelchair/High assistance", "Many/complex"): 1.40,
        }

        self.mc_care_level_add = {"Low": 0, "Medium": 600, "High": 1200}

    def _factor(self, location: str) -> float:
        return float(self.location_factor.get(location or "National", 1.00))

    def monthly_cost(self, inputs) -> int:
        ctype = getattr(inputs, "care_type", "none") or "none"
        loc = getattr(inputs, "location", "National") or "National"
        f = self._factor(loc)

        if ctype == "assisted_living":
            care = getattr(inputs, "al_care_level", "Low") or "Low"
            room = getattr(inputs, "al_room_type", "Studio") or "Studio"
            mob  = getattr(inputs, "al_mobility", "Independent") or "Independent"
            chrn = getattr(inputs, "al_chronic", "None") or "None"

            base = self.base_assisted_living
            add = self.al_care_level_add.get(care, 0) \
                + self.al_room_add.get(room, 0) \
                + self.mobility_add.get(mob, 0) \
                + self.chronic_add.get(chrn, 0)
            return int(round((base + add) * f))

        if ctype == "in_home":
            hpd = int(getattr(inputs, "ih_hours_per_day", 4) or 4)
            dpm = int(getattr(inputs, "ih_days_per_month", 20) or 20)
            mob  = getattr(inputs, "ih_mobility", "Independent") or "Independent"
            chrn = getattr(inputs, "ih_chronic", "None") or "None"

            hourly = self.base_in_home_hourly * f
            mult = self.ih_complexity_mult.get((mob, chrn), 1.0)
            return int(round(hourly * hpd * dpm * mult))

        if ctype == "memory_care":
            care = getattr(inputs, "mc_care_level", "Low") or "Low"
            mob  = getattr(inputs, "mc_mobility", "Independent") or "Independent"
            chrn = getattr(inputs, "mc_chronic", "None") or "None"

            base = self.base_memory_care + self.mc_care_level_add.get(care, 0)
            add = self.mobility_add.get(mob, 0) + self.chronic_add.get(chrn, 0)
            return int(round((base + add) * f))

        return 0
