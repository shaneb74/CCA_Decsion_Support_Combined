
import json
import random
from types import SimpleNamespace

class PlannerResult:
    def __init__(self, care_type, flags=None, scores=None, reasons=None, narrative=None):
        self.care_type = care_type
        self.flags = set(flags or [])
        self.scores = dict(scores or {})
        self.reasons = list(reasons or [])
        self.narrative = narrative

class PlannerEngine:
    """
    Loads Q&A and recommendation JSON and evaluates answers into a care_type and narrative.
    Defensive by design: works whether answers are strings or numeric codes mapped to labels upstream.
    """
    def __init__(self, qa_path: str, rec_path: str):
        with open(qa_path, "r") as f:
            self.qa = json.load(f)
        with open(rec_path, "r") as f:
            self.rec = json.load(f)
        # Cache useful sections
        self.questions = self.qa.get("questions", [])
        self.scoring_cfg = (self.rec.get("scoring") or {})
        self.thresholds = (self.rec.get("final_decision_thresholds") or {
            "assisted_living_min": 6, "in_home_min": 3, "dependence_flags_min": 2
        })
        self.rules = (self.rec.get("final_recommendation") or {})
        self.precedence = list(self.rec.get("decision_precedence", []))

    # -------------------- Helpers --------------------
    def _pick(self, arr, fallback):
        try:
            return random.choice(arr) if arr else fallback
        except Exception:
            return fallback

    def _render_message(self, template, name="", key_issues="", home_pref="default"):
        greeting = self._pick(self.rec.get("greeting_templates"), "Hello")
        positive = self._pick(self.rec.get("positive_state_templates"), "doing well")
        encourage = self._pick(self.rec.get("encouragement_templates"), "Stay strong")
        pref_map = self.rec.get("preference_clause_templates") or {}
        pref_arr = pref_map.get(home_pref) or pref_map.get("default") or ["Let’s find the best fit for you."]
        pref = self._pick(pref_arr, "Let’s find the best fit for you.")
        try:
            return template.format(
                greeting=greeting,
                name=name or "",
                key_issues=key_issues or "your situation",
                preference_clause=pref,
                positive_state=positive,
                encouragement=encourage,
                home_preference=("prefer home" if home_pref != "open_to_move" else "open to move"),
            )
        except Exception:
            # If template has mismatched tokens, just concatenate safely
            return f"{greeting} {name}. {pref}"

    def _answer_to_texts(self, answers: dict):
        """
        Normalize answer payload to plain strings for heuristic flag detection.
        Upstream may pass radio labels directly; if numeric codes are passed, we cannot decode here,
        so we just cast to str.
        """
        texts = []
        for k, v in answers.items():
            if k.startswith("_"):  # meta keys
                continue
            if isinstance(v, str):
                texts.append(v.lower())
            elif isinstance(v, (int, float)):
                texts.append(str(v))
            elif isinstance(v, (list, tuple)):
                texts.extend([str(x).lower() for x in v])
            else:
                texts.append(str(v).lower())
        return texts

    def _derive_flags_and_reasons(self, answers: dict):
        texts = self._answer_to_texts(answers)
        flags = set()
        reasons = []

        def add(flag, phr):
            flags.add(flag)
            if phr not in reasons:
                reasons.append(phr)

        # Heuristics based on common labels from your forms
        for t in texts:
            if any(x in t for x in ["wheelchair", "bedbound", "non-ambulatory"]):
                add("high_mobility_dependence", "significant mobility challenges")
            if any(x in t for x in ["cane", "walker", "needs help to move", "assisted (cane/walker)"]):
                add("moderate_mobility", "uses a cane/walker or needs help to move")
            if any(x in t for x in ["severe memory", "advanced dementia", "wandering", "unsafe alone with memory"]):
                add("severe_cognitive_risk", "severe memory/cognitive risk")
            if any(x in t for x in ["memory issues", "mild dementia", "cognitive decline", "forgetful"]):
                add("moderate_cognitive_decline", "memory or focus challenges")
            if any(x in t for x in ["no support", "alone", "no one helps", "no caregiver", "lives alone and no support"]):
                add("no_support", "no regular caregiver support")
            if any(x in t for x in ["frequent falls", "unsafe at home", "high fall risk", "emergency risks"]):
                add("high_safety_concern", "safety risks at home")
            if any(x in t for x in ["some fall risk", "occasionally unsafe"]):
                add("moderate_safety_concern", "some safety concerns at home")
            if any(x in t for x in ["overwhelmed caregiver", "care burden high"]):
                add("high_dependence", "needs extensive help with daily activities")
            if any(x in t for x in ["limited support", "infrequent help"]):
                add("limited_support", "limited caregiver support")

        return flags, reasons

    def _score(self, flags: set):
        # Use scoring config if present, else a sane fallback
        in_home = 0
        al = 0
        mem = 0

        # Scoring config per-domain weights are not strictly necessary here;
        # we derive compact scores from flags to align with thresholds.
        # Strong triggers for AL
        if "high_dependence" in flags: al += 3
        if "no_support" in flags: al += 2
        if "high_mobility_dependence" in flags: al += 2
        if "high_safety_concern" in flags: al += 2
        if "moderate_safety_concern" in flags: al += 1
        if "limited_support" in flags: al += 1
        if "moderate_mobility" in flags: al += 1

        # Memory care
        if "severe_cognitive_risk" in flags: mem += 3
        if "moderate_cognitive_decline" in flags: mem += 1; al += 1

        # In-home score emphasizes manageable situations
        if "moderate_mobility" in flags: in_home += 2
        if "limited_support" in flags: in_home += 1
        if "moderate_safety_concern" in flags: in_home += 1

        return {"in_home": in_home, "assisted_living": al, "memory_care": mem}

    def run(self, answers: dict, conditional_answer=None):
        name = answers.get("_person_name", "")
        home_pref = answers.get("_home_pref", "default")

        # Derive flags, reasons, scores
        flags, reasons = self._derive_flags_and_reasons(answers)
        scores = self._score(flags)
        in_home_score = scores.get("in_home", 0)
        al_score = scores.get("assisted_living", 0)
        mem_score = scores.get("memory_care", 0)

        assisted_min = int(self.thresholds.get("assisted_living_min", 6))
        inhome_min = int(self.thresholds.get("in_home_min", 3))
        dep_min = int(self.thresholds.get("dependence_flags_min", 2))

        # Zero-risk short-circuit
        if not flags and in_home_score == 0 and al_score == 0 and mem_score == 0:
            rule = (self.rules or {}).get("no_care_needed", {})
            tmpl = rule.get("message_template") or "{greeting} {name}, you’re {positive_state} with **no support needs** right now. {encouragement} — we’re here if things change. {preference_clause}"
            narrative = self._render_message(tmpl, name=name, key_issues="no current risks", home_pref=home_pref)
            return PlannerResult("none", flags, scores, reasons, narrative)

        # Rule evaluation by precedence
        outcome = None
        narrative = None
        rules = self.rules or {}

        def hit(rule_key):
            r = rules.get(rule_key) or {}
            tmpl = r.get("message_template") or "{greeting} {name}. {preference_clause}"
            msg = self._render_message(tmpl, name=name, key_issues=", ".join(reasons) if reasons else "your situation", home_pref=home_pref)
            return r.get("outcome"), msg

        # Evaluate explicit precedence we know about
        for key in (self.precedence or []):
            if key == "memory_care_override":
                if "severe_cognitive_risk" in flags and ({"no_support", "high_dependence", "high_safety_concern"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "dependence_flag_logic":
                count = len({"high_dependence", "high_mobility_dependence", "no_support", "severe_cognitive_risk", "high_safety_concern"} & flags)
                if count >= dep_min:
                    outcome, narrative = hit(key); break
            elif key == "assisted_living_score":
                if al_score >= assisted_min:
                    outcome, narrative = hit(key); break
            elif key == "balanced_al":
                if al_score >= assisted_min and in_home_score >= inhome_min and not ({"high_dependence", "high_mobility_dependence", "no_support", "high_safety_concern", "severe_cognitive_risk"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "in_home_with_mobility_challenges":
                if al_score >= (assisted_min - 1) and in_home_score >= inhome_min and "high_mobility_dependence" in flags and not ({"moderate_cognitive_decline", "severe_cognitive_risk"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "in_home_possible_with_cognitive_and_safety_risks":
                if in_home_score >= inhome_min and al_score >= inhome_min and ({"moderate_cognitive_decline", "severe_cognitive_risk", "moderate_safety_concern", "high_safety_concern"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "in_home_with_support_and_financial_needs":
                if in_home_score >= inhome_min and al_score < assisted_min and ("needs_financial_assistance" in flags or "limited_support" in flags):
                    outcome, narrative = hit(key); break
            elif key == "independent_with_safety_concern":
                if ({"moderate_safety_concern","high_safety_concern"} & flags) and not ({"severe_cognitive_risk","high_dependence","high_mobility_dependence"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "independent_no_support_risk":
                if "no_support" in flags and not ({"severe_cognitive_risk","high_mobility_dependence","high_dependence"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "no_care_needed":
                if al_score < inhome_min and in_home_score < inhome_min and not ({"high_dependence","high_mobility_dependence","no_support","severe_cognitive_risk","high_safety_concern","moderate_cognitive_decline","moderate_safety_concern"} & flags):
                    outcome, narrative = hit(key); break
            elif key == "in_home_with_support_fallback":
                # skip here; we use as final fallback
                pass

        if not outcome:
            fb = rules.get("in_home_with_support_fallback") or {}
            outcome = fb.get("outcome", "in_home")
            tmpl = fb.get("message_template") or "{greeting} {name}. {preference_clause}"
            narrative = self._render_message(tmpl, name=name, key_issues=", ".join(reasons) if reasons else "your situation", home_pref=home_pref)

        return PlannerResult(outcome, flags, scores, reasons, narrative)

class CalculatorEngine:
    """Placeholder; your real calculator is separate. This keeps interface stable."""
    def monthly_cost(self, inputs: SimpleNamespace):
        # Minimal demo: in_home lower, memory_care highest
        ct = getattr(inputs, "care_type", "in_home")
        if ct == "memory_care":
            base = 7000
        elif ct == "assisted_living":
            base = 5000
        elif ct == "none":
            base = 0
        else:
            # in-home uses hours * days * rate as example
            h = int(getattr(inputs, "in_home_hours_per_day", 4) or 4)
            d = int(getattr(inputs, "in_home_days_per_month", 20) or 20)
            rate = 35
            base = h * d * rate
        return base

def make_inputs(**kwargs):
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj
