# engines.py — Best-fit recommendation selector (JSON-first, safe fallback)
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# -------------------------------------------------------------------
# Feature flags / constants
# -------------------------------------------------------------------
ENGINE_STRICT_JSON = os.environ.get("ENGINE_STRICT_JSON", "false").lower() in {"1", "true", "yes", "on"}

# Severity ordering for tie-breaks (higher wins when weights tie)
SEVERITY_RANK = {
    "memory_care": 3,
    "assisted_living": 2,
    "in_home": 1,
    "none": 0,
}

# -------------------------------------------------------------------
# Public data structures
# -------------------------------------------------------------------
@dataclass
class PlannerResult:
    care_type: str                    # "in_home" | "assisted_living" | "memory_care" | "none"
    flags: List[str]
    scores: Dict[str, int]
    reasons: List[str]                # debug lines (we preserve your existing field name)
    narrative: str
    raw_rule: Optional[str] = None    # rule id chosen


# -------------------------------------------------------------------
# Utility exported for compatibility (some older app builds import this)
# -------------------------------------------------------------------
def resolve_narrative(template: str, ctx: Dict[str, Any]) -> str:
    """Safely format a message template with context."""
    safe = {k: ("" if v is None else v) for k, v in ctx.items()}
    try:
        return template.format(**safe)
    except Exception:
        return template


# -------------------------------------------------------------------
# Engine
# -------------------------------------------------------------------
class PlannerEngine:
    """
    Reads Q&A JSON and Recommendation JSON (same directory as app),
    converts answer dict {"q1": int, ...} into a PlannerResult.
    """

    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Rules + precedence from JSON
        self.rules: Dict[str, Dict[str, Any]] = self.rec.get("final_recommendation", {}) or {}
        self.precedence: List[str] = self.rec.get("decision_precedence", list(self.rules.keys()))

        # Thresholds (accept ints or strings like ">= 6")
        th = self.rec.get("final_decision_thresholds", {}) or {}
        self.in_home_min = self._parse_num(th.get("in_home_min"), 3)
        self.al_min = self._parse_num(th.get("assisted_living_min"), 6)

        # Dependence count (how many “red” flags trigger dependence rule)
        dep_cfg = self.rec.get("dependence_flag_logic", {}) or {}
        self.dep_min = self._parse_num(dep_cfg.get("dependence_flags_min"), 2)
        # explicit list of severe/critical flags to count if present
        self.dep_trigger_list: List[str] = dep_cfg.get(
            "trigger_if_flags",
            ["high_dependence", "high_mobility_dependence", "no_support",
             "severe_cognitive_risk", "high_safety_concern"]
        )

        # flag -> category mapping used for scoring
        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {}) or {}

        # category -> score weights per outcome family
        scoring = self.rec.get("scoring", {}) or {}
        self.score_in_home: Dict[str, int] = scoring.get("in_home", {}) or {}
        self.score_al: Dict[str, int] = scoring.get("assisted_living", {}) or {}

    # --------------------------- Public API ---------------------------
    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule, outcome, trace = self._choose_best_rule(flags, scores)
        narrative = self._render(rule, flags, scores, name)

        # Append candidate trace into reasons for on-screen transparency
        if trace:
            debug.append(trace)

        return PlannerResult(
            care_type=outcome,
            flags=sorted(flags),
            scores=scores,
            reasons=debug,
            narrative=narrative,
            raw_rule=rule,
        )

    # -------------------------- Evaluation ---------------------------
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        """Turn raw answers into flags + scores using JSON triggers + flag_to_category_mapping."""
        flags: Set[str] = set()
        debug: List[str] = []

        # IMPORTANT: UI saves questions as q1..qN (1-based)
        for idx, q in enumerate(self.qa.get("questions", []), start=1):
            qk = f"q{idx}"
            a = answers.get(qk)
            if a is None:
                continue

            triggers = q.get("trigger", {}) or {}
            for _cat, tlist in triggers.items():
                for t in tlist or []:
                    try:
                        if "answer" in t and int(t["answer"]) == int(a):
                            fl = t.get("flag")
                            if fl:
                                flags.add(fl)
                                debug.append(f"q{idx}={a} → flag {fl}")
                    except Exception:
                        # Be permissive—ignore malformed trigger rows
                        continue

        # Map flags → categories for scoring
        cats: Set[str] = set()
        for fl in flags:
            c = self.flag_to_cat.get(fl)
            if c:
                cats.add(c)

        if cats:
            debug.append(f"• categories: {sorted(cats)}")

        in_home_score = sum(self.score_in_home.get(c, 0) for c in cats)
        al_score = sum(self.score_al.get(c, 0) for c in cats)

        scores = {
            "in_home_score": int(in_home_score),
            "assisted_living_score": int(al_score),
        }
        debug.append(f"• scores: in_home={scores['in_home_score']} al={scores['assisted_living_score']}")
        return flags, scores, debug

    # ------------------------- Rule Selection ------------------------
    def _choose_best_rule(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str, str]:
        """
        Build *all* matching candidates then choose the best by weight.
        JSON-defined conditions (when present) are honored first; otherwise
        we fall back to name-based handlers to avoid breaking older files.
        """
        # Context for generic JSON matcher
        ctx = {
            "flags": flags,
            "scores": scores,
            "in_min": self.in_home_min,
            "al_min": self.al_min,
            "dep_min": self.dep_min,
        }

        candidates: List[Tuple[float, str, str, str]] = []  # (weight, rule_name, outcome, reason)

        # Helper for precedence weight (later rules can be weaker or stronger depending on style).
        # We bias *higher* precedence (earlier in the list) by giving them a small head start,
        # but still allow stronger evidence to beat.
        max_prec = max(len(self.precedence), 1)
        def prec_bonus(i: int) -> float:
            return (max_prec - i) * 1.0  # small linear bonus

        # Build candidates
        for i, rule in enumerate(self.precedence):
            meta = self.rules.get(rule, {}) or {}
            explicit = self._json_conditions_present(meta)
            matched = False
            reason = ""

            if ENGINE_STRICT_JSON and explicit:
                matched, reason = self._match_json(meta, ctx)
            elif ENGINE_STRICT_JSON and not explicit:
                matched = False
                reason = "skipped (no JSON conditions)"
            else:
                # Non-strict: prefer JSON conditions if present; else fallback to legacy name-based
                if explicit:
                    matched, reason = self._match_json(meta, ctx)
                if not explicit or not matched:
                    ok = self._legacy_match(rule, ctx)
                    matched = matched or ok
                    if ok and not reason:
                        reason = "legacy-match"

            if not matched:
                continue

            outcome = self._infer_outcome(rule, meta)
            # Weight:
            w = float(meta.get("weight", 0)) + prec_bonus(i)
            # Strengthen by score proximity to thresholds
            w += 0.5 * (scores.get("assisted_living_score", 0) / max(self.al_min, 1))
            w += 0.25 * (scores.get("in_home_score", 0) / max(self.in_home_min, 1))
            # Small severity bias to prefer safer recommendation when equally plausible
            w += 0.1 * SEVERITY_RANK.get(outcome, 0)

            candidates.append((w, rule, outcome, reason))

        # Fallbacks if nothing matched
        if not candidates:
            if "in_home_with_support_fallback" in self.rules:
                return "in_home_with_support_fallback", "in_home", "fallback"
            return "no_care_needed", "none", "fallback"

        # Choose best weight; break ties by severity rank
        candidates.sort(key=lambda x: (x[0], SEVERITY_RANK.get(x[2], 0)))
        best_w, best_rule, best_outcome, why = candidates[-1]

        # Build trace line for UI
        def fmt(c: Tuple[float, str, str, str]) -> str:
            w, r, o, y = c
            return f"{r}->{o} (w={int(round(w*10))//10})"
        trace = "• CANDIDATES: " + " | ".join(fmt(c) for c in candidates) + f"\n\n• CHOICE: {why} -> {best_outcome}"
        return best_rule, best_outcome, trace

    # ---------- JSON condition matching (generic, data-driven) -------
    def _json_conditions_present(self, meta: Dict[str, Any]) -> bool:
        keys = {
            "require_flags_all", "require_flags_any", "forbid_flags_any",
            "min_scores", "dependence_at_least", "min_assisted_living",
            "min_in_home",
        }
        return any(k in meta for k in keys)

    def _match_json(self, meta: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[bool, str]:
        f = ctx["flags"]; s = ctx["scores"]
        # flags
        req_all = set(meta.get("require_flags_all", []) or [])
        req_any = set(meta.get("require_flags_any", []) or [])
        forb   = set(meta.get("forbid_flags_any", []) or [])

        if req_all and not req_all.issubset(f):
            return False, "require_all_failed"
        if req_any and not (req_any & f):
            return False, "require_any_failed"
        if forb and (forb & f):
            return False, "forbid_failed"

        # scores
        mins = meta.get("min_scores", {}) or {}
        need_in  = self._parse_num(mins.get("in_home_score"), None)
        need_al  = self._parse_num(mins.get("assisted_living_score"), None)
        if need_in is not None and s.get("in_home_score", 0) < need_in:
            return False, "min_in_home_score_failed"
        if need_al is not None and s.get("assisted_living_score", 0) < need_al:
            return False, "min_al_score_failed"

        # convenience shortcuts some JSONs use
        min_al_simple = self._parse_num(meta.get("min_assisted_living"), None)
        if min_al_simple is not None and s.get("assisted_living_score", 0) < min_al_simple:
            return False, "min_al_failed"

        min_in_simple = self._parse_num(meta.get("min_in_home"), None)
        if min_in_simple is not None and s.get("in_home_score", 0) < min_in_simple:
            return False, "min_in_failed"

        # dependence count
        need_dep = self._parse_num(meta.get("dependence_at_least"), None)
        if need_dep is not None:
            got = sum(1 for x in self.dep_trigger_list if x in f)
            if got < need_dep:
                return False, "dependence_count_failed"

        return True, "json-conditions"

    # ---------------- Legacy name-based handlers (compat) ------------
    def _legacy_match(self, rule_name: str, ctx: Dict[str, Any]) -> bool:
        """Maintain behavior for older JSONs that relied on engine logic names."""
        f = ctx["flags"]; s = ctx["scores"]
        in_min = ctx["in_min"]; al_min = ctx["al_min"]; dep_min = ctx["dep_min"]

        def any_of(*need: str) -> bool: return any(n in f for n in need)
        def all_of(*need: str) -> bool: return all(n in f for n in need)
        def none_of(*ban: str) -> bool: return all(n not in f for n in ban)

        if rule_name == "memory_care_override":
            return "severe_cognitive_risk" in f and any_of("no_support", "high_safety_concern")

        if rule_name == "dependence_flag_logic":
            count = sum(1 for x in self.dep_trigger_list if x in f)
            return count >= dep_min

        if rule_name in {"assisted_living", "assisted_living_score", "assisted_living_core"}:
            return s["assisted_living_score"] >= al_min

        if rule_name == "moderate_needs_assisted_living_recommendation":
            return (s["assisted_living_score"] >= al_min and
                    s["in_home_score"] >= in_min and
                    all_of("moderate_dependence", "moderate_mobility", "moderate_cognitive_decline"))

        if rule_name == "close_to_assisted_living_with_moderate_needs":
            return (s["assisted_living_score"] >= al_min - 1 and
                    s["in_home_score"] >= in_min and
                    all_of("moderate_dependence", "moderate_cognitive_decline"))

        if rule_name == "balanced_recommendation":
            return (s["assisted_living_score"] >= al_min and
                    s["in_home_score"] >= in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "high_safety_concern", "severe_cognitive_risk"))

        if rule_name == "in_home_with_mobility_challenges":
            return (s["assisted_living_score"] >= al_min - 1 and
                    s["in_home_score"] >= in_min and
                    "high_mobility_dependence" in f and
                    none_of("moderate_cognitive_decline", "severe_cognitive_risk"))

        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] >= in_min and
                    any_of("moderate_cognitive_decline", "severe_cognitive_risk",
                           "moderate_safety_concern", "high_safety_concern"))

        if rule_name == "in_home_with_support_and_financial_needs":
            return (s["in_home_score"] >= in_min and
                    s["assisted_living_score"] < al_min and
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
            return (s["assisted_living_score"] < in_min and
                    s["in_home_score"] < in_min and
                    none_of("high_dependence", "high_mobility_dependence", "no_support",
                            "severe_cognitive_risk", "high_safety_concern",
                            "moderate_cognitive_decline", "moderate_safety_concern", "high_risk"))

        if rule_name == "in_home_with_uncertain_support":
            return any_of("limited_support", "moderate_risk", "high_risk", "mental_health_concern",
                          "moderate_dependence", "moderate_mobility", "moderate_safety_concern",
                          "low_access", "very_low_access")

        return False

    def _infer_outcome(self, rule_name: str, meta: Dict[str, Any]) -> str:
        if meta.get("outcome"):
            return meta["outcome"]
        r = rule_name.lower()
        if "memory" in r:
            return "memory_care"
        if "assisted" in r or r.startswith("al_"):
            return "assisted_living"
        if "no_care" in r or "independent" in r or r.endswith("_none"):
            return "none"
        return "in_home"

    # ----------------------------- Narrative -------------------------
    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {}) or {}
        template = meta.get("message_template", "")

        # Build {key_issues} phrase from issue_phrases catalog (randomized)
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {}) or {}
        for flg in flags:
            opts = issue_catalog.get(flg)
            if opts:
                phrases.append(random.choice(opts))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        # Preference clause
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
            recommendation=self._infer_outcome(rule_name, meta).replace("_", " ").title(),
        )
        return resolve_narrative(template, ctx)

    # ----------------------------- Helpers ---------------------------
    def _rand(self, seq: List[str]) -> str:
        if not seq:
            return ""
        return random.choice(seq)

    @staticmethod
    def _parse_num(v: Any, default: Optional[int]) -> Optional[int]:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m:
                return int(m.group(1))
        return default


# -------------------------------------------------------------------
# Minimal calculator wrapper (unchanged behavior)
# -------------------------------------------------------------------
class CalculatorEngine:
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        base = {"in_home": 4000, "assisted_living": 6500, "memory_care": 8500, "none": 0}
        return int(base.get(care_type, 4000))


# -------------------------------------------------------------------
# Self-test harness (optional) — run: python engines.py
# -------------------------------------------------------------------
def _try(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return True
    except Exception:
        return False

def _selftest():
    root = Path(__file__).resolve().parent
    qa = root / "question_answer_logic_FINAL_UPDATED.json"
    rc = root / "recommendation_logic_FINAL_MASTER_UPDATED.json"
    if not (_try(qa) and _try(rc)):
        print("Self-test skipped (JSON files not found).")
        return

    pe = PlannerEngine(str(qa), str(rc))

    # 12 compact scenarios covering edges
    scenarios = {
        "zero_flags": {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": 1, "q6": 1, "q7": 1, "q8": 1, "q9": 1},
        "prefers_home_mod_risks": {"q1": 2, "q2": 3, "q3": 3, "q4": 2, "q5": 3, "q6": 2, "q7": 3, "q8": 3, "q9": 2},
        "al_heavy": {"q1": 2, "q2": 3, "q3": 3, "q4": 2, "q5": 3, "q6": 3, "q7": 3, "q8": 3, "q9": 1},
        "al_close": {"q1": 2, "q2": 3, "q3": 2, "q4": 2, "q5": 3, "q6": 2, "q7": 2, "q8": 2, "q9": 3},
        "mc_override": {"q1": 2, "q2": 4, "q3": 3, "q4": 3, "q5": 4, "q6": 4, "q7": 4, "q8": 3, "q9": 1},
        "independent_no_support": {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": 4, "q6": 1, "q7": 1, "q8": 1, "q9": 1},
        "independent_safety": {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": 1, "q6": 1, "q7": 3, "q8": 1, "q9": 1},
        "in_home_financial": {"q1": 3, "q2": 2, "q3": 1, "q4": 1, "q5": 2, "q6": 1, "q7": 1, "q8": 1, "q9": 2},
        "mobility_challenge": {"q1": 2, "q2": 2, "q3": 4, "q4": 2, "q5": 2, "q6": 1, "q7": 1, "q8": 1, "q9": 2},
        "uncertain_support": {"q1": 2, "q2": 2, "q3": 2, "q4": 2, "q5": 2, "q6": 2, "q7": 2, "q8": 2, "q9": 2},
        "geography_issue": {"q1": 2, "q2": 2, "q3": 2, "q4": 2, "q5": 2, "q6": 1, "q7": 1, "q8": 3, "q9": 2},
        "pref_home_low": {"q1": 2, "q2": 2, "q3": 2, "q4": 1, "q5": 2, "q6": 1, "q7": 1, "q8": 1, "q9": 3},
    }

    print(f"ENGINE_STRICT_JSON={ENGINE_STRICT_JSON}")
    for name, ans in scenarios.items():
        out = pe.run(ans, name="Test")
        print(f"{name:24s} -> {out.care_type:16s} | rule={out.raw_rule} | scores={out.scores}")

if __name__ == "__main__":
    _selftest()