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
            ["high_dependence", "high_mobility_dependence", "no_support",
             "severe_cognitive_risk", "high_safety_concern"]
        )

        scoring = self.rec.get("scoring", {}) or {}
        self.flag_to_cat: Dict[str, str] = self.rec.get("flag_to_category_mapping", {}) or {}
        self.score_in_home: Dict[str, int] = scoring.get("in_home", {}) or {}
        self.score_al: Dict[str, int] = scoring.get("assisted_living", {}) or {}

    def run(self, answers: Dict[str, int], *, name: str = "You") -> PlannerResult:
        flags, scores, debug = self._evaluate(answers)
        rule, outcome, trace = self._choose_best_rule(flags, scores)
        narrative = self._render(rule, flags, scores, name)
        if trace:
            debug.append(trace)
        return PlannerResult(outcome, sorted(flags), scores, debug, narrative, rule)

    # ---- internals ---------------------------------------------------
    def _evaluate(self, answers: Dict[str, int]) -> Tuple[Set[str], Dict[str, int], List[str]]:
        flags: Set[str] = set()
        debug: List[str] = []
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
                                debug.append(f"{qk}={a} → flag {fl}")
                    except Exception:
                        continue

        cats: Set[str] = set()
        for fl in flags:
            c = self.flag_to_cat.get(fl)
            if c:
                cats.add(c)
        if cats:
            debug.append(f"• categories: {sorted(cats)}")

        in_home_score = sum(self.score_in_home.get(c, 0) for c in cats)
        al_score      = sum(self.score_al.get(c, 0) for c in cats)
        scores = {"in_home_score": int(in_home_score), "assisted_living_score": int(al_score)}
        debug.append(f"• scores: in_home={scores['in_home_score']} al={scores['assisted_living_score']}")
        return flags, scores, debug

    def _choose_best_rule(self, flags: Set[str], scores: Dict[str, int]) -> Tuple[str, str, str]:
        ctx = {"flags": flags, "scores": scores, "in_min": self.in_home_min, "al_min": self.al_min, "dep_min": self.dep_min}
        candidates: List[Tuple[float, str, str, str]] = []
        max_prec = max(len(self.precedence), 1)
        def prec_bonus(i: int) -> float: return (max_prec - i) * 1.0

        for i, rule in enumerate(self.precedence):
            meta = self.rules.get(rule, {}) or {}
            explicit = self._json_has_conditions(meta)
            matched = False; reason = ""
            if ENGINE_STRICT_JSON and explicit:
                matched, reason = self._match_json(meta, ctx)
            elif ENGINE_STRICT_JSON and not explicit:
                matched = False; reason = "skipped(no-json)"
            else:
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
            w = float(meta.get("weight", 0)) + prec_bonus(i)
            w += 0.5 * (scores.get("assisted_living_score", 0) / max(self.al_min, 1))
            w += 0.25 * (scores.get("in_home_score", 0) / max(self.in_home_min, 1))
            w += 0.1 * SEVERITY_RANK.get(outcome, 0)
            candidates.append((w, rule, outcome, reason))

        if not candidates:
            if "in_home_with_support_fallback" in self.rules:
                return "in_home_with_support_fallback", "in_home", "fallback"
            return "no_care_needed", "none", "fallback"

        candidates.sort(key=lambda x: (x[0], SEVERITY_RANK.get(x[2], 0)))
        _, best_rule, best_outcome, why = candidates[-1]
        def fmt(c): w,r,o,y = c; return f"{r}->{o} (w={int(round(w*10))//10})"
        trace = "• CANDIDATES: " + " | ".join(fmt(c) for c in candidates) + f"\n\n• CHOICE: {why} -> {best_outcome}"
        return best_rule, best_outcome, trace

    def _json_has_conditions(self, meta: Dict[str, Any]) -> bool:
        keys = {"require_flags_all","require_flags_any","forbid_flags_any","min_scores","dependence_at_least","min_assisted_living","min_in_home"}
        return any(k in meta for k in keys)

    def _match_json(self, meta: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[bool, str]:
        f = ctx["flags"]; s = ctx["scores"]
        req_all = set(meta.get("require_flags_all", []) or [])
        req_any = set(meta.get("require_flags_any", []) or [])
        forb   = set(meta.get("forbid_flags_any", []) or [])

        if req_all and not req_all.issubset(f): return False, "require_all"
        if req_any and not (req_any & f):       return False, "require_any"
        if forb and (forb & f):                 return False, "forbid"

        mins = meta.get("min_scores", {}) or {}
        need_in = self._num(mins.get("in_home_score"), None)
        need_al = self._num(mins.get("assisted_living_score"), None)
        if need_in is not None and s.get("in_home_score", 0) < need_in: return False, "min_in"
        if need_al is not None and s.get("assisted_living_score", 0) < need_al: return False, "min_al"

        min_al_simple = self._num(meta.get("min_assisted_living"), None)
        if min_al_simple is not None and s.get("assisted_living_score", 0) < min_al_simple: return False, "min_al_simple"
        min_in_simple = self._num(meta.get("min_in_home"), None)
        if min_in_simple is not None and s.get("in_home_score", 0) < min_in_simple: return False, "min_in_simple"

        need_dep = self._num(meta.get("dependence_at_least"), None)
        if need_dep is not None:
            got = sum(1 for x in self.dep_trigger_list if x in f)
            if got < need_dep: return False, "dependence"
        return True, "json"

    def _legacy_match(self, rule_name: str, ctx: Dict[str, Any]) -> bool:
        f = ctx["flags"]; s = ctx["scores"]
        in_min = ctx["in_min"]; al_min = ctx["al_min"]; dep_min = ctx["dep_min"]
        def any_of(*need): return any(n in f for n in need)
        def all_of(*need): return all(n in f for n in need)
        def none_of(*ban): return all(n not in f for n in ban)

        if rule_name == "memory_care_override":
            return "severe_cognitive_risk" in f and any_of("no_support","high_safety_concern")
        if rule_name == "dependence_flag_logic":
            return sum(1 for x in ["high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk","high_safety_concern"] if x in f) >= dep_min
        if rule_name in {"assisted_living","assisted_living_score","assisted_living_core"}:
            return s["assisted_living_score"] >= al_min
        if rule_name == "balanced_recommendation":
            return (s["assisted_living_score"] >= al_min and s["in_home_score"] >= in_min and
                    none_of("high_dependence","high_mobility_dependence","no_support","high_safety_concern","severe_cognitive_risk"))
        if rule_name == "in_home_with_mobility_challenges":
            return (s["assisted_living_score"] >= al_min-1 and s["in_home_score"] >= in_min and
                    "high_mobility_dependence" in f and none_of("moderate_cognitive_decline","severe_cognitive_risk"))
        if rule_name == "in_home_possible_with_cognitive_and_safety_risks":
            return (s["in_home_score"] >= in_min and s["assisted_living_score"] >= in_min and
                    any_of("moderate_cognitive_decline","severe_cognitive_risk","moderate_safety_concern","high_safety_concern"))
        if rule_name == "in_home_with_support_and_financial_needs":
            return (s["in_home_score"] >= in_min and s["assisted_living_score"] < al_min and "needs_financial_assistance" in f)
        if rule_name == "independent_with_safety_concern":
            return (none_of("moderate_cognitive_decline","severe_cognitive_risk","high_dependence","high_mobility_dependence") and
                    any_of("moderate_safety_concern","high_safety_concern"))
        if rule_name == "independent_no_support_risk":
            return (none_of("moderate_cognitive_decline","severe_cognitive_risk","high_mobility_dependence") and "no_support" in f)
        if rule_name == "no_care_needed":
            return (s["assisted_living_score"] < in_min and s["in_home_score"] < in_min and
                    none_of("high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk",
                            "high_safety_concern","moderate_cognitive_decline","moderate_safety_concern","high_risk"))
        return False

    def _infer_outcome(self, rule_name: str, meta: Dict[str, Any]) -> str:
        if meta.get("outcome"): return meta["outcome"]
        r = rule_name.lower()
        if "memory" in r: return "memory_care"
        if "assisted" in r or r.startswith("al_"): return "assisted_living"
        if "no_care" in r or "independent" in r or r.endswith("_none"): return "none"
        return "in_home"

    def _render(self, rule_name: str, flags: Set[str], scores: Dict[str, int], name: str) -> str:
        meta = self.rules.get(rule_name, {}) or {}
        template = meta.get("message_template", "")
        phrases: List[str] = []
        issue_catalog: Dict[str, List[str]] = self.rec.get("issue_phrases", {}) or {}
        for flg in flags:
            opts = issue_catalog.get(flg)
            if opts:
                phrases.append(random.choice(opts))
        key_issues = ", ".join(phrases) if phrases else "your current situation"

        if "strongly_prefers_home" in flags: pref_key = "strongly_prefers_home"
        elif "prefers_home" in flags:        pref_key = "prefers_home"
        elif "open_to_move" in flags:        pref_key = "open_to_move"
        else:                                pref_key = "default"
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
            recommendation=self._infer_outcome(rule_name, meta).replace("_"," ").title(),
        )
        return resolve_narrative(template, ctx)

    def _rand(self, seq: List[str]) -> str:
        if not seq: return ""
        return random.choice(seq)

    @staticmethod
    def _num(v: Any, default: Optional[int]) -> Optional[int]:
        if v is None: return default
        if isinstance(v, (int,float)): return int(v)
        if isinstance(v, str):
            m = re.search(r"(\d+)", v)
            if m: return int(m.group(1))
        return default

# -------------------- COST ENGINE (real math) -----------------------

class CalculatorEngine:
    """
    Pure function of inputs -> monthly dollars.
    Expects a SimpleNamespace or object with attributes set by cost_controls:
      care_type: "assisted_living" | "in_home" | "memory_care" | "none"
      location_factor: float
      # Assisted Living fields:
      al_care_level: str   # "Light", "Moderate", "High"
      al_room_type: str    # "Studio", "1 Bedroom", "2 Bedroom", "Shared"
      al_mobility: str     # "None", "Walker", "Wheelchair"
      al_chronic: str      # "None", "Diabetes", "Parkinson's", "Complex"
      # In-Home fields:
      ih_hours_per_day: int
      ih_days_per_month: int
      ih_mobility: str
      ih_chronic: str
      # Memory Care fields:
      mc_level: str        # "Standard", "High Acuity"
      mc_mobility: str
      mc_chronic: str
    """
    def __init__(self, *args, **kwargs):
        pass

    def monthly_cost(self, inputs: Any) -> int:
        ct = getattr(inputs, "care_type", "in_home")
        lf = float(getattr(inputs, "location_factor", 1.0))

        if ct == "assisted_living":
            base = 5500.0
            care_add = {
                "Light": 0, "Moderate": 900, "High": 1800
            }.get(getattr(inputs, "al_care_level", "Light"), 0)
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
            rate = 35.0 * lf
            hpd  = int(getattr(inputs, "ih_hours_per_day", 4) or 4)
            dpm  = int(getattr(inputs, "ih_days_per_month", 20) or 20)
            mobility_mult = {"None": 1.0, "Walker": 1.05, "Wheelchair": 1.1}.get(getattr(inputs, "ih_mobility", "None"), 1.0)
            chronic_mult  = {"None": 1.0, "Diabetes": 1.05, "Parkinson's": 1.12, "Complex": 1.2}.get(getattr(inputs, "ih_chronic", "None"), 1.0)
            return int(round(rate * hpd * dpm * mobility_mult * chronic_mult))

        if ct == "memory_care":
            base = 8200.0
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

# --- Injected safety override ---
def dependence_override(flags: set[str]) -> bool:
    """Return True if high dependence risk warrants an assisted living override."""
    _dep = {"high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk","high_safety_concern"}
    return sum(1 for f in _dep if f in flags) >= 2
