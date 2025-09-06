# engines.py — Fixed scoring via flag mapping, care type inference, and threshold parsing
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import random
import re

@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
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

        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rec.get("final_recommendation", {}).keys()))
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.thresholds = self.rec.get("final_decision_thresholds", {})
        self.in_home_min = 3
        self.al_min = 6
        self.dep_min = 2
        # Parse descriptive thresholds
        for k, v in self.thresholds.items():
            m = re.search(r'>=\s*(\d+)', v)
            if m:
                num = int(m.group(1))
                if "assisted_living" in k.lower():
                    self.al_min = num
                if "in_home" in k.lower():
                    self.in_home_min = num
        # dep_min from dependence_flag_logic criteria
        dep_criteria = self.rec.get("dependence_flag_logic", {}).get("criteria", "")
        m = re.search(r'(\d+) or more', dep_criteria)
        if m:
            self.dep_min = int(m.group(1))

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule_name, outcome = self._decide(flags, scores)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule_name,
        )

    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []

        for q_idx, question in enumerate(self.qa.get("questions", [])):
            qk = f"q{q_idx}"
            ans_val = answers.get(qk)
            if ans_val is None:
                continue

            for category, tlist in question.get("trigger", {}).items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == ans_val:
                        flag = t.get("flag")
                        if flag:
                            flags.add(flag)
                            debug.append(f"{qk} ans {ans_val} → flag {flag} (category: {category})")

        # Map flags to categories for scoring
        mapping = self.rec.get("flag_to_category_mapping", {})
        triggered_categories = set(mapping.get(flag) for flag in flags if flag in mapping)
        if triggered_categories:
            debug.append(f"Mapped triggered categories: {sorted(triggered_categories)}")

        in_home_score = sum(self.rec["scoring"]["in_home"].get(cat, 0) for cat in triggered_categories)
        al_score = sum(self.rec["scoring"]["assisted_living"].get(cat, 0) for cat in triggered_categories)
        if triggered_categories:
            debug.append(f"Scores: in_home={in_home_score}, al={al_score}")

        scores = {
            "in_home_score": in_home_score,
            "assisted_living_score": al_score,
        }
        return flags, scores, debug

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        ctx = {
            "flags": flags,
            "scores": scores,
            "in_min": self.in_home_min,
            "al_min": self.al_min,
            "dep_min": self.dep_min,
        }

        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                continue
            if self._match(rule, meta, ctx):
                outcome = meta.get("outcome", None)
                if outcome is None:
                    # Infer from rule name
                    r_lower = rule.lower()
                    if "memory_care" in r_lower:
                        outcome = "memory_care"
                    elif "assisted_living" in r_lower or "al" in r_lower:
                        outcome = "assisted_living"
                    elif "no_care" in r_lower or "independent" in r_lower:
                        outcome = "none"
                    else:
                        outcome = "in_home"
                return rule, outcome

        # Fallback
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        if "in_home_with_support" in self.rules:
            return "in_home_with_support", "in_home"
        return "no_care_needed", "none"

    def _match(self, rule_name: str, meta: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
        f = ctx["flags"]
        s = ctx["scores"]

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "memory_care_override":
            return "severe_cognitive_risk" in f and "no_support" in f

        if rule_name == "dependence_flag_logic":
            ctr = sum(n in f for n in self.rec.get("dependence_flag_logic", {}).get("trigger_if_flags", []))
            return ctr >= ctx["dep_min"]

        if rule_name == "social_isolation_warning":
            return any_of("high_risk", "mental_health_concern")

        if rule_name == "cognitive_decline_warning":
            return any_of("moderate_cognitive_decline", "severe_cognitive_risk")

        if rule_name == "assisted_living":
            return s["assisted_living_score"] >= ctx["al_min"]

        if rule_name == "moderate_needs_assisted_living_recommendation":
            return (s["assisted_living_score"] >= ctx["al_min"] and
                    s["in_home_score"] >= ctx["in_min"] and
                    all_of("moderate_dependence", "moderate_mobility", "moderate_cognitive_decline"))

        if rule_name == "close_to_assisted_living_with_moderate_needs":
            return (s["assisted_living_score"] >= ctx["al_min"] - 1 and
                    s["in_home_score"] >= ctx["in_min"] and
                    all_of("moderate_dependence", "moderate_cognitive_decline"))

        if rule_name == "balanced_recommendation":
            return (s["assisted_living_score"] >= ctx["al_min"] and
                    s["in_home_score"] >= ctx["in_min"] and
                    none_of("high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk"))

        if rule_name == "in_home_with_mobility_challenges":
            return (s["assisted_living_score"] >= ctx["al_min"] - 1 and
                    s["in_home_score"] >= ctx["in_min"] and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home_score"] >= ctx["in_min"] and
                    s["assisted_living_score"] >= ctx["in_min"] and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk", "moderate_safety_concern", "high_safety_concern"))

        if rule_name == "in_home_with_support_and_financial_needs":
            return (s["in_home_score"] >= ctx["in_min"] and
                    s["assisted_living_score"] < ctx["al_min"] and
                    "needs_financial_assistance" in f)

        if rule_name == "in_home_low_support_financial_needs":
            return ("needs_financial_assistance" in f and
                    "limited_support" in f and
                    none_of("moderate_safety_concern", "high_safety_concern", "moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence"))

        if rule_name == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_dependence", "high_mobility_dependence") and
                    any_of("moderate_safety_concern", "high_safety_concern"))

        if rule_name == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence") and
                    "no_support" in f)

        if rule_name == "no_care_needed":
            return (s["assisted_living_score"] < ctx["in_min"] and
                    s["in_home_score"] < ctx["in_min"] and
                    none_of(
                        "high_dependence", "high_mobility_dependence", "no_support",
                        "severe_cognitive_risk", "high_safety_concern", "moderate_cognitive_decline",
                        "moderate_safety_concern", "high_risk"
                    ))

        if rule_name == "in_home_with_uncertain_support":
            return any_of(
                "limited_support", "moderate_risk", "high_risk", "mental_health_concern",
                "moderate_dependence", "moderate_mobility", "moderate_safety_concern",
                "low_access", "very_low_access"
            )

        # Fallback for unhandled rules
        return True

    # ------------- narrative rendering -------------
    def _rand(self, seq: List[str]) -> str:
        if not seq: return ""
        return random.choice(seq)

    def _render_message(self, template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            return template

    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        # Build {key_issues}
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            if flg in issue_catalog and issue_catalog[flg]:
                phrases.append(random.choice(issue_catalog[flg]))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # Build {preference_clause}
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
            recommendation=meta.get("outcome", "in-home care").replace("_", " ").title(),
        )
        return self._render_message(template, ctx)


# CalculatorEngine wrapper (unchanged)
class CalculatorEngine:
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))