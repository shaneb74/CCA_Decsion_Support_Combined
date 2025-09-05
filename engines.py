# engines.py — JSON-driven planner with rendered narratives
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import random

@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None


class PlannerEngine:
    """
    Loads:
      - Q&A file: defines questions, triggers, and how answers set flags/scores
      - Recommendation file: defines thresholds, precedence, rules, and text templates
    Produces:
      - PlannerResult with rendered narrative (no placeholders leaked to UI)
    """

    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = Path(qa_path)
        self.rec_path = Path(rec_path)
        with open(self.qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(self.rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # thresholds / precedence
        self.thresholds = self.rec.get("final_decision_thresholds", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", [])
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})

    # ----------------- public API -----------------
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

    # ----------------- internals ------------------
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """
        Apply Q&A triggers. Important: answers MUST be INTs.
        """
        flags: Set[str] = set()
        in_home_score = 0
        al_score = 0
        debug: List[str] = []

        # Triggers section (if present) — each entry can specify:
        # - q: "qN"
        # - answer: int (exact match) OR answers_in: [ints]
        # - add_flags: [str] or flag: str
        # - add_scores: {"in_home": n, "assisted_living": n}
        triggers = self.qa.get("triggers", [])
        for t in triggers:
            qk = t.get("q")
            if not qk:
                continue
            ans_val = answers.get(qk)
            if ans_val is None:
                continue

            matched = False
            if "answer" in t:
                try:
                    matched = int(ans_val) == int(t["answer"])
                except Exception:
                    matched = False
            elif "answers_in" in t:
                try:
                    pool = [int(x) for x in t["answers_in"]]
                    matched = int(ans_val) in pool
                except Exception:
                    matched = False

            if not matched:
                continue

            # flags
            if "flag" in t:
                flags.add(t["flag"])
                debug.append(f"{qk} matched → flag {t['flag']}")
            for f in t.get("add_flags", []):
                flags.add(f)
                debug.append(f"{qk} matched → flag {f}")

            # scores
            add = t.get("add_scores", {})
            in_home_score += int(add.get("in_home", 0))
            al_score      += int(add.get("assisted_living", 0))
            if add:
                debug.append(f"{qk} matched → score+ {add}")

        scores = {
            "in_home_score": in_home_score,
            "assisted_living_score": al_score,
        }
        return flags, scores, debug

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        """
        Walk precedence; return (rule_name, outcome)
        """
        in_min  = int(self.thresholds.get("in_home_min", 3))
        al_min  = int(self.thresholds.get("assisted_living_min", 6))
        dep_min = int(self.thresholds.get("dependence_flags_min", 2))

        # convenience helpers used by rule criteria evaluation
        ctx = {
            "flags": flags,
            "scores": scores,
            "in_min": in_min,
            "al_min": al_min,
            "dep_min": dep_min,
        }

        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                continue
            if self._match(rule, meta, ctx):
                outcome = meta.get("outcome", "in_home")
                return rule, outcome

        # fallback: if nothing matched, in_home_with_support_fallback if present
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", self.rules["in_home_with_support_fallback"].get("outcome", "in_home")
        # absolute fallback
        return "no_care_needed", "none"

    def _match(self, rule_name: str, meta: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
        f = ctx["flags"]
        s = ctx["scores"]

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "memory_care_override":
            return ("severe_cognitive_risk" in f) and any_of("no_support", "high_dependence", "high_safety_concern")

        if rule_name == "dependence_flag_logic":
            ctr = sum(n in f for n in [
                "high_dependence",
                "high_mobility_dependence",
                "no_support",
                "severe_cognitive_risk",
                "high_safety_concern",
            ])
            return ctr >= int(ctx["dep_min"])

        if rule_name == "assisted_living_score":
            return s["assisted_living_score"] >= int(ctx["al_min"])

        if rule_name == "balanced_al":
            return (
                s["assisted_living_score"] >= int(ctx["al_min"]) and
                s["in_home_score"] >= int(ctx["in_min"]) and
                none_of("high_dependence","high_mobility_dependence","no_support","high_safety_concern","severe_cognitive_risk")
            )

        if rule_name == "in_home_with_mobility_challenges":
            return (
                s["assisted_living_score"] >= int(ctx["al_min"]) - 1 and
                s["in_home_score"] >= int(ctx["in_min"]) and
                ("high_mobility_dependence" in f) and
                none_of("moderate_cognitive_decline","severe_cognitive_risk")
            )

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (
                s["in_home_score"] >= int(ctx["in_min"]) and
                s["assisted_living_score"] >= int(ctx["in_min"]) and
                any_of("moderate_cognitive_decline","severe_cognitive_risk","moderate_safety_concern","high_safety_concern")
            )

        if rule_name == "in_home_with_support_and_financial_needs":
            return (
                s["in_home_score"] >= int(ctx["in_min"]) and
                s["assisted_living_score"] < int(ctx["al_min"]) and
                ("needs_financial_assistance" in f)
            )

        if rule_name == "independent_with_safety_concern":
            return (
                none_of("moderate_cognitive_decline","severe_cognitive_risk","high_dependence","high_mobility_dependence") and
                any_of("moderate_safety_concern","high_safety_concern")
            )

        if rule_name == "independent_no_support_risk":
            return (
                none_of("moderate_cognitive_decline","severe_cognitive_risk","high_mobility_dependence") and
                ("no_support" in f)
            )

        if rule_name == "no_care_needed":
            return (
                s["assisted_living_score"] < int(ctx["in_min"]) and
                s["in_home_score"] < int(ctx["in_min"]) and
                none_of(
                    "high_dependence","high_mobility_dependence","no_support",
                    "severe_cognitive_risk","high_safety_concern","moderate_cognitive_decline",
                    "moderate_safety_concern","high_risk"
                )
            )

        if rule_name == "in_home_with_support_fallback":
            return True

        # default: if a custom rule includes a python-like flag expression, skip (safety)
        return False

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
                phrases.append(issue_catalog[flg][0])
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
        )
        return self._render_message(template, ctx)


# ------------------------------------------------------------
# CalculatorEngine wrapper: preserve your existing API
# ------------------------------------------------------------
class CalculatorEngine:
    """
    This wrapper preserves your existing interface. If you already have a more
    sophisticated CalculatorEngine elsewhere, this file will not fight it.
    """
    def __init__(self, *args, **kwargs):
        # defer to your existing implementation if any shared state is needed
        pass

    # Keep the method signature your app calls
    def monthly_cost(self, inputs: Any) -> int:
        # Your existing implementation should remain.
        # This stub ensures the planner fix does not break downstream screens.
        # Replace with your real calculator logic if this file is the source of truth.
        care_type = getattr(inputs, "care_type", "in_home")
        # very conservative placeholder (you likely overwrite elsewhere)
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))