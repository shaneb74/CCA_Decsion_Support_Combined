# engines.py — Evidence-based planner with score-guaranteed AL candidate
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ----------------------------- Data model -----------------------------

@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]                # human-readable debug trail
    narrative: str
    raw_rule: Optional[str] = None    # rule label that ultimately won (for audit)


# ----------------------------- Planner Engine -----------------------------

class PlannerEngine:
    """
    Converts answers {"q1": int, ...} into flags, scores, and a recommended care_type
    using:
      - question_answer_logic JSON (triggers -> flags)
      - recommendation_logic JSON (flag_to_category_mapping, scoring, templates)
    """

    # ---- ctor ----
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {})
        self.precedence: List[str] = self.rec.get(
            "decision_precedence", list(self.rules.keys())
        )

        # thresholds: accept ints or strings like ">= 6"
        th = self.rec.get("final_decision_thresholds", {})
        self.in_home_min = self._num(th.get("in_home_min"), 3)
        self.al_min      = self._num(th.get("assisted_living_min"), 6)
        self.dep_min     = self._num(th.get("dependence_flags_min"), 2)

        # Ranking weights (higher wins). JSON can override these keys.
        # Strong bias for safety-first decisions.
        self.rank_weights: Dict[str, int] = {
            "memory_care_override": 100,
            "memory_care": 90,
            "assisted_living_score": 70,
            "assisted_living": 70,
            "balanced_al": 65,
            "in_home_possible_with_cognitive_and_safety_risks": 50,
            "in_home_with_mobility_challenges": 45,
            "in_home_with_support_and_financial_needs": 40,
            "in_home_low_support_financial_needs": 35,
            "in_home_score": 30,
            "in_home_with_support_fallback": 25,
            "independent_with_safety_concern": 20,
            "independent_no_support_risk": 15,
            "no_care_needed": 10,
        }
        self.rank_weights.update(self.rec.get("rank_weights", {}))

        # Dependence count flags list (fallback if JSON omits)
        self.dep_flags = self.rec.get("dependence_flag_logic", {}).get(
            "trigger_if_flags",
            ["high_dependence", "high_mobility_dependence", "no_support",
             "severe_cognitive_risk", "high_safety_concern"]
        )

    # ---- public API ----
    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule_name, outcome = self._decide_best(flags, scores, debug)
        narrative = self._render(rule_name, flags, scores, name)
        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule_name,
        )

    # ---- answers -> flags -> scores ----
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []

        # 1-based q-index (app saves as "q1","q2",...)
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            for _cat, tlist in (q.get("trigger", {}) or {}).items():
                for t in tlist:
                    try:
                        if "answer" in t and int(t["answer"]) == int(a):
                            fl = t.get("flag")
                            if fl:
                                flags.add(fl)
                                debug.append(f"• {qk}={a} → flag {fl}")
                    except Exception:
                        continue

        # Map flags to categories
        cat_map: Dict[str, str] = self.rec.get("flag_to_category_mapping", {})
        cats: Set[str] = set()
        for fl in flags:
            c = cat_map.get(fl)
            if c:
                cats.add(c)
        if cats:
            debug.append(f"• categories: {sorted(cats)}")

        # Score by category weights
        in_home_score = sum(self.rec["scoring"]["in_home"].get(c, 0) for c in cats)
        al_score      = sum(self.rec["scoring"]["assisted_living"].get(c, 0) for c in cats)

        scores = {"in_home_score": in_home_score, "assisted_living_score": al_score}
        debug.append(f"• scores: in_home={in_home_score} al={al_score}")
        return flags, scores, debug

    # ---- best decision: collect candidates, guarantee AL/IH by score, pick max weight ----
    def _decide_best(self, flags: Set[str], scores: Dict[str, int], debug: List[str]) -> Tuple[str, str]:
        candidates: List[Tuple[int, str, str]] = []  # (weight, rule_name, outcome)
        f, s = flags, scores

        # 1) Hard override for Memory Care
        if "severe_cognitive_risk" in f and ("no_support" in f or "high_safety_concern" in f):
            w = self.rank_weights.get("memory_care_override", 100)
            candidates.append((w, "memory_care_override", "memory_care"))

        # 2) Evaluate JSON rules (when they explicitly match)
        for rule in self.precedence:
            meta = self.rules.get(rule) or {}
            if self._match(rule, meta, f, s):
                outcome = meta.get("outcome")
                if not outcome:
                    r = rule.lower()
                    if "memory" in r: outcome = "memory_care"
                    elif "assisted" in r or "al_" in r: outcome = "assisted_living"
                    elif "no_care" in r or "none" in r: outcome = "none"
                    else: outcome = "in_home"
                w = self.rank_weights.get(rule, self._default_weight(outcome))
                candidates.append((w, rule, outcome))

        # 3) **Guarantee** Assisted Living & In-home candidates by thresholds,
        #    so AL can *never* be missed due to a misnamed/missing rule.
        if s.get("assisted_living_score", 0) >= self.al_min:
            w = self.rank_weights.get("assisted_living_score", 70)
            candidates.append((w, "assisted_living_score", "assisted_living"))

        if s.get("in_home_score", 0) >= self.in_home_min:
            w = self.rank_weights.get("in_home_score", 30)
            candidates.append((w, "in_home_score", "in_home"))

        # 4) Edge case: no candidates → graceful fallbacks
        if not candidates:
            # if literally no flags/scores, it's safe to say "none"
            if s.get("assisted_living_score", 0) < self.in_home_min and s.get("in_home_score", 0) < self.in_home_min:
                candidates.append((self.rank_weights.get("no_care_needed", 10), "no_care_needed", "none"))
            else:
                candidates.append((self.rank_weights.get("in_home_with_support_fallback", 25),
                                   "in_home_with_support_fallback", "in_home"))

        # 5) Pick highest weight; break ties by safer outcome
        candidates.sort(key=lambda t: (t[0], self._safety_rank(t[2])), reverse=True)
        w, rule_name, outcome = candidates[0]

        # Debug trail
        dbg = " | ".join(f"{r}→{o} (w={w})" for (w, r, o) in candidates)
        debug.append(f"• CANDIDATES: {dbg}")
        debug.append(f"• CHOICE: {rule_name} → {outcome}")
        return rule_name, outcome

    # ---- JSON rule matcher (lightweight; named handlers where needed) ----
    def _match(self, rule_name: str, meta: Dict[str, Any],
               flags: Set[str], scores: Dict[str, int]) -> bool:
        f, s = flags, scores

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "dependence_flag_logic":
            cnt = sum(1 for fl in self.dep_flags if fl in f)
            return cnt >= self.dep_min

        if rule_name in ("assisted_living", "assisted_living_score"):
            return s.get("assisted_living_score", 0) >= self.al_min

        if rule_name == "balanced_al":
            return (s.get("assisted_living_score", 0) >= self.al_min and
                    s.get("in_home_score", 0) >= self.in_home_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk"))

        if rule_name == "in_home_with_mobility_challenges":
            return (s.get("assisted_living_score", 0) >= self.al_min - 1 and
                    s.get("in_home_score", 0) >= self.in_home_min and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s.get("in_home_score", 0) >= self.in_home_min and
                    s.get("assisted_living_score", 0) >= self.in_home_min and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                           "moderate_safety_concern", "high_safety_concern"))

        if rule_name == "in_home_with_support_and_financial_needs":
            return (s.get("in_home_score", 0) >= self.in_home_min and
                    s.get("assisted_living_score", 0) < self.al_min and
                    "needs_financial_assistance" in f)

        if rule_name == "in_home_low_support_financial_needs":
            return ("needs_financial_assistance" in f and
                    "limited_support" in f and
                    none_of("moderate_safety_concern", "high_safety_concern",
                            "moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_mobility_dependence"))

        if rule_name == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_dependence", "high_mobility_dependence") and
                    any_of("moderate_safety_concern", "high_safety_concern"))

        if rule_name == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline", "severe_cognitive_risk",
                            "high_mobility_dependence") and
                    "no_support" in f)

        if rule_name == "no_care_needed":
            return (s.get("assisted_living_score", 0) < self.in_home_min and
                    s.get("in_home_score", 0) < self.in_home_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "severe_cognitive_risk", "high_safety_concern",
                            "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        # Unknown rule: allow it so message/outcome can still be rendered
        return True

    # ---- narrative rendering ----
    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {})
        template = meta.get("message_template", "")

        # build {key_issues}
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {})
        for flg in flags:
            bank = issue_catalog.get(flg)
            if bank:
                phrases.append(random.choice(bank))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # build {preference_clause}
        if "strongly_prefers_home" in flags:
            pref_key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            pref_key = "prefers_home"
        elif "open_to_move" in flags:
            pref_key = "open_to_move"
        else:
            pref_key = "default"
        preference_clause = self._choose(self.rec.get("preference_clause_templates", {}).get(pref_key, [""]))

        greeting       = self._choose(self.rec.get("greeting_templates", ["Hello"]))
        positive_state = self._choose(self.rec.get("positive_state_templates", ["doing well"]))
        encouragement  = self._choose(self.rec.get("encouragement_templates", ["We’re here for you."]))

        ctx = dict(
            name=name,
            key_issues=key_issues,
            preference_clause=preference_clause,
            greeting=greeting,
            positive_state=positive_state,
            encouragement=encouragement,
            home_preference=("prefer to stay home" if ("prefers_home" in flags or "strongly_prefers_home" in flags)
                             else "are open to moving"),
            recommendation=(meta.get("outcome", "in_home").replace("_", " ").title()),
        )
        return self._format(template, ctx)

    # ------------------------- helpers -------------------------

    @staticmethod
    def _num(v: Any, default: int) -> int:
        if isinstance(v, (int, float)): return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m: return int(m.group(1))
        return default

    @staticmethod
    def _choose(seq: List[str]) -> str:
        return random.choice(seq) if seq else ""

    @staticmethod
    def _format(template: str, ctx: Dict[str, Any]) -> str:
        safe = {k: ("" if v is None else v) for k, v in ctx.items()}
        try:
            return template.format(**safe)
        except Exception:
            return template

    @staticmethod
    def _default_weight(outcome: str) -> int:
        if outcome == "memory_care": return 90
        if outcome == "assisted_living": return 70
        if outcome == "in_home": return 30
        return 10

    @staticmethod
    def _safety_rank(outcome: str) -> int:
        # tie-breaker: safer options rank higher
        order = {"memory_care": 3, "assisted_living": 2, "in_home": 1, "none": 0}
        return order.get(outcome, 0)


# ----------------------------- Calculator stub (unchanged) -----------------------------

class CalculatorEngine:
    """Very light placeholder — your real pricing model can live elsewhere."""
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))