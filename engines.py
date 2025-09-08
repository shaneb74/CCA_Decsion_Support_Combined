# engines.py — Self-contained planner/calculator engines with robust flagging & strict rule matching
from __future__ import annotations

import json
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# --------------------------- Data objects ---------------------------

@dataclass
class PlannerResult:
    care_type: str                    # "none" | "in_home" | "assisted_living" | "memory_care"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]                # human-friendly trace of what fired
    narrative: str
    raw_rule: Optional[str] = None    # which rule selected


# --------------------------- Planner Engine ---------------------------

class PlannerEngine:
    """
    Pure, self-contained recommendation engine.
    - Reads Q&A JSON and Recommendation JSON.
    - Accepts answers dict: { "q1": int, "q2": int, ... } (1-based).
    - Returns PlannerResult (care_type + flags + scores + narrative).
    """

    def __init__(self, qa_path: str | Path, rec_path: str | Path):
        qa_path = str(qa_path)
        rec_path = str(rec_path)

        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Core blocks from recommendation JSON
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))
        self.thresholds: Dict[str, Any] = self.rec.get("final_decision_thresholds", {})

        # Thresholds: accept ints or strings like ">= 6"
        def _num(v: Any, default: int) -> int:
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                m = re.search(r"(\d+)", v)
                if m:
                    return int(m.group(1))
            return default

        self.in_home_min = _num(self.thresholds.get("in_home_min"), 3)
        self.al_min      = _num(self.thresholds.get("assisted_living_min"), 6)
        self.dep_min     = _num(self.thresholds.get("dependence_flags_min"), 2)

        # Flag → category map for scoring, with a safe fallback
        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {}) or {}
        if not self.flag_to_cat:
            # Conservative inference (keeps you off all-zero scoring if mapping omitted)
            # You can extend this as needed; unknowns fall into "home_safety"
            self.flag_to_cat = {
                "high_dependence": "care_burden",
                "moderate_dependence": "care_burden",
                "high_mobility_dependence": "care_burden",
                "moderate_mobility": "care_burden",

                "high_risk": "social_isolation",
                "moderate_risk": "social_isolation",
                "mental_health_concern": "mental_health_concern",

                "no_support": "financial_feasibility",
                "limited_support": "financial_feasibility",
                "needs_financial_assistance": "financial_feasibility",
                "moderate_financial_concern": "financial_feasibility",
                "can_afford_care": "financial_feasibility",

                "moderate_safety_concern": "home_safety",
                "high_safety_concern": "home_safety",

                "low_access": "geographic_access",
                "very_low_access": "geographic_access",

                "mild_cognitive_decline": "cognitive_function",
                "moderate_cognitive_decline": "cognitive_function",
                "severe_cognitive_risk": "cognitive_function",
            }

        # Scoring tables must exist
        self.score_inhome: Dict[str, int] = (self.rec.get("scoring", {}) or {}).get("in_home", {}) or {}
        self.score_al: Dict[str, int]     = (self.rec.get("scoring", {}) or {}).get("assisted_living", {}) or {}
        # If scoring is missing, keep sane defaults to avoid “no_care_needed” dominating
        if not self.score_inhome:
            self.score_inhome = {k: 1 for k in set(self.flag_to_cat.values())}
        if not self.score_al:
            self.score_al = {k: 2 for k in set(self.flag_to_cat.values())}

    # ---------- public API ----------

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, trace = self._evaluate(answers)
        rule_name, outcome = self._decide(flags, scores)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=trace,
            narrative=narrative,
            raw_rule=rule_name,
        )

    # ---------- internals ----------

    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """
        Compute flags and scores from Q&A JSON.
        - Questions are 1-based: q1..qN
        - Triggers live under each question's `trigger` map.
        """
        flags: Set[str] = set()
        trace: List[str] = []

        # Walk questions 1..N, not 0..N-1
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qkey = f"q{idx}"
            ans_val = answers.get(qkey, None)
            if ans_val is None:
                continue

            trig = q.get("trigger", {})
            if not isinstance(trig, dict):
                continue

            # Each trigger category has a list of patterns {answer, flag}
            for _cat, tlist in trig.items():
                if not isinstance(tlist, list):
                    continue
                for t in tlist:
                    try:
                        if "answer" in t and int(t["answer"]) == int(ans_val):
                            fl = t.get("flag")
                            if fl:
                                flags.add(fl)
                                trace.append(f"{qkey}={ans_val} → flag '{fl}'")
                    except Exception:
                        # if JSON contained non-int 'answer', ignore gracefully
                        continue

        # Map flags → scoring categories
        cats: Set[str] = set()
        for fl in flags:
            cat = self.flag_to_cat.get(fl)
            if cat:
                cats.add(cat)

        if cats:
            trace.append(f"categories: {sorted(cats)}")

        in_home_score = sum(self.score_inhome.get(c, 0) for c in cats)
        al_score      = sum(self.score_al.get(c, 0) for c in cats)
        scores = {"in_home_score": in_home_score, "assisted_living_score": al_score}
        trace.append(f"scores: in_home={in_home_score}, assisted_living={al_score}")

        # Quick visibility on high-severity flags
        for hard_flag in ("severe_cognitive_risk", "high_safety_concern", "high_dependence", "no_support"):
            if hard_flag in flags:
                trace.append(f"hard-flag: {hard_flag}")

        return flags, scores, trace

    def _decide(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str]:
        """
        Strict, precedence-driven selector.
        Unknown rules DO NOT match by default (prevents “always-true”).
        """
        f = flags
        s = scores
        in_min = self.in_home_min
        al_min = self.al_min
        dep_min = self.dep_min

        def has_any(*need: str) -> bool: return any(n in f for n in need)
        def has_all(*need: str) -> bool: return all(n in f for n in need)
        def has_none(*ban: str) -> bool: return all(n not in f for n in ban)

        # Safety net: obvious memory care override
        if "severe_cognitive_risk" in f and has_any("no_support", "high_safety_concern"):
            return "memory_care_override", "memory_care"

        for rule in self.precedence:
            meta = self.rules.get(rule, {})
            if not meta:
                continue

            # Handlers for named rules (aligns with your JSON names)
            matched = False

            if rule == "dependence_flag_logic":
                to_count = meta.get("trigger_if_flags", [
                    "high_dependence", "high_mobility_dependence", "no_support",
                    "severe_cognitive_risk", "high_safety_concern"
                ])
                count = sum(1 for fl in to_count if fl in f)
                matched = (count >= dep_min)

            elif rule == "assisted_living_score":
                matched = (s["assisted_living_score"] >= al_min)

            elif rule == "balanced_al":
                matched = (
                    s["assisted_living_score"] >= al_min and
                    s["in_home_score"] >= in_min and
                    has_none("high_dependence", "high_mobility_dependence", "no_support",
                             "high_safety_concern", "severe_cognitive_risk")
                )

            elif rule == "in_home_with_mobility_challenges":
                matched = (
                    s["assisted_living_score"] >= (al_min - 1) and
                    s["in_home_score"] >= in_min and
                    "high_mobility_dependence" in f and
                    has_none("moderate_cognitive_decline", "severe_cognitive_risk")
                )

            elif rule == "in_home_possible_with_cognitive_and_safety_risks":
                matched = (
                    s["in_home_score"] >= in_min and
                    s["assisted_living_score"] >= in_min and
                    has_any("moderate_cognitive_decline", "severe_cognitive_risk",
                            "moderate_safety_concern", "high_safety_concern")
                )

            elif rule == "in_home_with_support_and_financial_needs":
                matched = (
                    s["in_home_score"] >= in_min and
                    s["assisted_living_score"] < al_min and
                    "needs_financial_assistance" in f
                )

            elif rule == "independent_with_safety_concern":
                matched = (
                    has_none("moderate_cognitive_decline", "severe_cognitive_risk",
                             "high_dependence", "high_mobility_dependence")
                    and has_any("moderate_safety_concern", "high_safety_concern")
                )

            elif rule == "independent_no_support_risk":
                matched = (
                    has_none("moderate_cognitive_decline", "severe_cognitive_risk",
                             "high_mobility_dependence")
                    and ("no_support" in f)
                )

            elif rule == "no_care_needed":
                matched = (
                    s["assisted_living_score"] < in_min and
                    s["in_home_score"] < in_min and
                    has_none("high_dependence", "high_mobility_dependence", "no_support",
                             "severe_cognitive_risk", "high_safety_concern",
                             "moderate_cognitive_decline", "moderate_safety_concern", "high_risk")
                )

            else:
                # Unknown rule names: DO NOT match by default (prevents accidental “always-true”)
                matched = False

            if matched:
                outcome = meta.get("outcome")
                if not outcome:
                    # Infer outcome from rule name if author omitted it
                    r = rule.lower()
                    if "memory" in r:
                        outcome = "memory_care"
                    elif "assisted" in r or "al_" in r:
                        outcome = "assisted_living"
                    elif "no_care" in r or "independent" in r:
                        outcome = "none"
                    else:
                        outcome = "in_home"
                return rule, outcome

        # If nothing matched, choose an explicit fallback when present
        if "in_home_with_support_fallback" in self.rules:
            return "in_home_with_support_fallback", "in_home"
        return "no_care_needed", "none"

    # ---------- narrative rendering ----------

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

        # key_issues
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            arr = issue_catalog.get(flg)
            if arr:
                phrases.append(self._rand(arr))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # preference clause
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
            home_preference=("prefer to stay home"
                             if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                             else "are open to moving"),
            recommendation=(meta.get("outcome", "in-home care").replace("_", " ").title()),
        )
        return self._render_message(template, ctx)


# --------------------------- Convenience for app.py ---------------------------

def resolve_narrative(rec_block: Dict[str, Any]) -> str:
    """
    Backward-compatible helper for older app code that expects to pull a message
    from a result dict. Use with PlannerResult.__dict__ or your stored dict.
    """
    return (
        rec_block.get("narrative")
        or rec_block.get("advisory")
        or rec_block.get("message")
        or rec_block.get("message_rendered")
        or rec_block.get("message_template")
        or ""
    )


# --------------------------- Calculator Engine (unchanged API) ---------------------------

class CalculatorEngine:
    """
    Very light placeholder. Your real pricing logic can replace this
    without changing the call sites in app.py or cost_controls.py.
    """
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        # Simple baselines; your cost engine likely multiplies by state factors,
        # care level, mobility, chronic conditions, hours/days, etc.
        base = {
            "none": 0,
            "in_home": 4000,
            "assisted_living": 6500,
            "memory_care": 8500,
        }
        return int(base.get(care_type, 4000))