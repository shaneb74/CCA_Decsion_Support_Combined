import json
import random

class PlannerResult:
    def __init__(self, care_type, flags=None, scores=None, reasons=None, advisory=None):
        self.care_type = care_type
        self.flags = flags or set()
        self.scores = scores or {}
        self.reasons = reasons or []
        self.advisory = advisory

class PlannerEngine:
    def __init__(self, qa_path, rec_path):
        with open(qa_path, "r") as f:
            self.qa = json.load(f)
        with open(rec_path, "r") as f:
            self.rec = json.load(f)
        self.questions = self.qa.get("questions", [])

    def run(self, answers):
        # Derive flags and scores
        flags = set()
        scores = {}
        reasons = []

        for q in self.questions:
            qid = q.get("id")
            if qid in answers:
                ans = answers[qid]
                if isinstance(ans, str) and "wheelchair" in ans.lower():
                    flags.add("high_mobility_dependence")
                    reasons.append("using a wheelchair or major mobility help")
                if isinstance(ans, str) and "memory" in ans.lower():
                    flags.add("moderate_cognitive_decline")
                    reasons.append("memory or focus challenges")

        scores["in_home"] = len([f for f in flags if "mobility" in f])
        scores["assisted_living"] = len(flags)
        scores["memory_care"] = 1 if "moderate_cognitive_decline" in flags else 0

        outcome = "in_home"
        narrative = None

        precedence = self.rec.get("decision_precedence", [])
        final_rules = self.rec.get("final_recommendation", {})

        for rule_key in precedence:
            rule = final_rules.get(rule_key)
            if not rule:
                continue
            crit = rule.get("criteria", "").lower()

            if "severe_cognitive_risk" in flags or "memory care" in crit:
                outcome = "memory_care"
                narrative = rule.get("message_template")
                break
            if "assisted living" in crit and scores.get("assisted_living", 0) >= 2:
                outcome = "assisted_living"
                narrative = rule.get("message_template")
                break

        if not narrative:
            fallback = final_rules.get("in_home_with_support_fallback", {})
            narrative = fallback.get("message_template")
            outcome = fallback.get("outcome", "in_home")

        greeting = random.choice(self.rec.get("greeting_templates", ["Hello"]))
        preference = random.choice(self.rec.get("preference_clause_templates", {}).get("default", ["Let's find the best fit for you."]))
        narrative = narrative.format(
            greeting=greeting,
            name="",
            key_issues=", ".join(reasons) if reasons else "your situation",
            preference_clause=preference,
            positive_state="doing well",
            encouragement="Stay strong",
            home_preference="prefer home"
        )

        return PlannerResult(outcome, flags, scores, reasons, narrative)

class CalculatorEngine:
    def run(self, inputs):
        base_cost = 3000 if inputs.care_type == "in_home" else 5000
        return {
            "monthly_cost": base_cost,
            "annual_cost": base_cost * 12
        }

def make_inputs(**kwargs):
    from types import SimpleNamespace
    obj = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj
