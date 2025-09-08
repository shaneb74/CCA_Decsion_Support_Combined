# engines.py — Planner + Recommendation engine (fixed precedence matching)
from __future__ import annotations

import json
import re
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------- Data model ----------
@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]
    narrative: str
    raw_rule: Optional[str] = None


# ---------- Planner / Recommender ----------
class PlannerEngine:
    """
    Reads Q&A JSON and Recommendation JSON (expected by app.py to be in repo root),
    evaluates answers => flags & scores, then picks a final recommendation using
    decision_precedence + rule handlers, and renders a narrative.
    """

    def __init__(self, qa_path: str, rec_path: str):
        # Load JSONs
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Rule table & precedence (keep file order if precedence not provided)
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))

        # Thresholds (accept ints or strings like ">= 6")
        self.in_home_min = 3
        self.al_min = 6
        self.dep_min = 2

        th = self.rec.get("final_decision_thresholds", {})

        def _num(v, default):
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                m = re.search(r"(\d+)", v)
                if m:
                    return int(m.group(1))
            return default

        self.in_home_min = _num(th.get("in_home_min"), self.in_home_min)
        self.al_min = _num(th.get("assisted_living_min"), self.al_min)
        self.dep_min = _num(th.get("dependence_flags_min"), self.dep_min)

    # -------- public API --------
    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        """
        Answers are 1-based keys: {"q1": 2, "q2": 1, ...}
        """
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

    # -------- internals --------
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """Turn raw answers into flags + scores using JSON triggers + flag_to_category_mapping."""
        flags: Set[str] = set()
        debug: List[str] = []

        # IMPORTANT: UI saves answers as q1..qN (1-based)
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            triggers = q.get("trigger", {})
            for _cat, tlist in triggers.items():
                for t in tlist:
                    if "answer" in t and int(t["answer"]) == int(a):
                        fl = t.get("flag")
                        if fl:
                            flags.add(fl)
                            debug.append(f"{qk}={a} → flag {fl}")

        # Map flags → scoring categories
        cat_map: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})
        triggered_categories: Set[str] = set()
        for fl in flags:
            if fl in cat_map:
                triggered_categories.add(cat_map[fl])

        if triggered_categories:
            debug.append(f"categories: {sorted(triggered_categories)}")

        in_home_score = sum(self.rec["scoring"]["in_home"].get(c, 0) for c in triggered_categories)
        al_score = sum(self.rec["scoring"]["assisted_living"].get(c, 0) for c in triggered_categories)

        scores = {
            "in_home_score": in_home_score,
            "assisted_living_score": al_score,
        }
        debug.append(f"scores: in_home={in_home_score} al={al_score}")
        return flags, scores, debug

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        """
        Walk precedence and pick the first matching rule; infer outcome when omitted.
        Ensures rules can't match by default.
        """
        ctx = {
            "flags": flags,
            "scores": scores,
            "in_min": self.in_home_min,
            "al_min": self.al_min,
            "dep_min": self.dep_min,
        }

        def any_of(*need: str) -> bool:
            return any(n in flags for n in need)

        # Fast memory-care override (explicit safetynet)
        if "severe_cognitive_risk" in flags and any_of("no_support", "high_safety_concern"):
            return "memory_care_override", "memory_care"

        # Precedence loop
        for rule in self.precedence:
            meta = self.rules.get(rule)
            if not meta:
                continue
            if self._match(rule, meta, ctx, flags, scores):
                outcome = meta.get("outcome")
                if not outcome:
                    r = rule.lower()
                    if "memory" in r:
                        outcome = "memory_care"
                    elif "assisted" in r or "al_" in r:
                        outcome = "assisted_living"
                    elif "no_care" in r or "none" in r or "independent" in r:
                        outcome = "none"
                    else:
                        outcome = "in_home"
                return rule, outcome

        # Fallbacks (if nothing matched)
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        return "no_care_needed", "none"

    def _match(
        self,
        rule_name: str,
        meta: Dict[str, Any],
        ctx: Dict[str, Any],
        flags: Set[str],
        scores: Dict[str, int],
    ) -> bool:
        """
        Custom handlers for rule names we know; for unknown rules return False so they
        don't accidentally match just because they appear early in precedence.
        """
        f = flags
        s = scores
        in_min = ctx["in_min"]
        al_min = ctx["al_min"]
        dep_min = ctx["dep_min"]

        def any_of(*need: str) -> bool:
            return any(n in f for n in need)

        def all_of(*need: str) -> bool:
            return all(n in f for n in need)

        def none_of(*ban: str) -> bool:
            return all(n not in f for n in ban)

        # --- Explicit handlers that must never auto-match ---

        if rule_name == "memory_care_override":
            # Only true with severe cognitive risk + (no support OR high safety concern)
            return ("severe_cognitive_risk" in f) and ("no_support" in f or "high_safety_concern" in f)

        if rule_name == "dependence_flag_logic":
            to_count = (
                self.rec.get("final_recommendation", {})
                .get("dependence_flag_logic", {})
                .get(
                    "trigger_if_flags",
                    [
                        "high_dependence",
                        "high_mobility_dependence",
                        "no_support",
                        "severe_cognitive_risk",
                        "high_safety_concern",
                    ],
                )
            )
            count = sum(1 for fl in to_count if fl in f)
            return count >= dep_min

        if rule_name == "assisted_living_score":
            return s.get("assisted_living_score", 0) >= al_min

        if rule_name == "balanced_al":
            return (
                s.get("assisted_living_score", 0) >= al_min
                and s.get("in_home_score", 0) >= in_min
                and none_of(
                    "high_dependence",
                    "high_mobility_dependence",
                    "no_support",
                    "high_safety_concern",
                    "severe_cognitive_risk",
                )
            )

        if rule_name == "in_home_with_mobility_challenges":
            return (
                s.get("assisted_living_score", 0) >= (al_min - 1)
                and s.get("in_home_score", 0) >= in_min
                and "high_mobility_dependence" in f
                and none_of("moderate_cognitive_decline", "severe_cognitive_risk")
            )

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (
                s.get("in_home_score", 0) >= in_min
                and s.get("assisted_living_score", 0) >= in_min
                and any_of(
                    "moderate_cognitive_decline",
                    "severe_cognitive_risk",
                    "moderate_safety_concern",
                    "high_safety_concern",
                )
            )

        if rule_name == "in_home_with_support_and_financial_needs":
            return (
                s.get("in_home_score", 0) >= in_min
                and s.get("assisted_living_score", 0) < al_min
                and "needs_financial_assistance" in f
            )

        if rule_name == "independent_with_safety_concern":
            return (
                none_of(
                    "moderate_cognitive_decline",
                    "severe_cognitive_risk",
                    "high_dependence",
                    "high_mobility_dependence",
                )
                and any_of("moderate_safety_concern", "high_safety_concern")
            )

        if rule_name == "independent_no_support_risk":
            return (
                none_of("moderate_cognitive_decline", "severe_cognitive_risk", "high_mobility_dependence")
                and "no_support" in f
            )

        if rule_name == "no_care_needed":
            return (
                s.get("assisted_living_score", 0) < in_min
                and s.get("in_home_score", 0) < in_min
                and none_of(
                    "high_dependence",
                    "high_mobility_dependence",
                    "no_support",
                    "severe_cognitive_risk",
                    "high_safety_concern",
                    "moderate_cognitive_decline",
                    "moderate_safety_concern",
                    "high_risk",
                )
            )

        # Unknown rule names: do NOT match by default
        return False

    # ------------- narrative rendering -------------
    def _rand(self, seq: List[str]) -> str:
        if not seq:
            return ""
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

        # {key_issues}
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            if flg in issue_catalog and issue_catalog[flg]:
                phrases.append(random.choice(issue_catalog[flg]))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # {preference_clause}
        if "strongly_prefers_home" in flags:
            pref_key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            pref_key = "prefers_home"
        elif "open_to_move" in flags:
            pref_key = "open_to_move"
        else:
            pref_key = "default"
        preference_clause = self._rand(self.rec.get("preference_clause_templates", {}).get(pref_key, [""]))

        greeting = self._rand(self.rec.get("greeting_templates", ["Hello"]))
        positive_state = self._rand(self.rec.get("positive_state_templates", ["doing well"]))
        encouragement = self._rand(self.rec.get("encouragement_templates", ["We’re here for you."]))

        ctx = dict(
            name=name,
            key_issues=key_issues,
            preference_clause=preference_clause,
            greeting=greeting,
            positive_state=positive_state,
            encouragement=encouragement,
            home_preference=(
                "prefer to stay home"
                if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                else "are open to moving"
            ),
            recommendation=meta.get("outcome", "in-home care").replace("_", " ").title(),
        )
        return self._render_message(template, ctx)


# ---------- Cost shim (unchanged placeholder) ----------
class CalculatorEngine:
    """Very light placeholder — your pricing model can live elsewhere."""
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))