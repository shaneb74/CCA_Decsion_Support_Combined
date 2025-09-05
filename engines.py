
# engines.py — JSON-driven PlannerEngine + CalculatorEngine (hardened)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Set, Any, Optional
import json
from pathlib import Path
import math
import itertools

@dataclass
class PlannerResult:
    care_type: str
    flags: Set[str] = field(default_factory=set)
    scores: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    advisory: Optional[str] = None
    message: Optional[str] = None
    message_rendered: Optional[str] = None

def _safe_get(dct: dict, *keys, default=None):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

class PlannerEngine:
    """
    Reads Q/A and recommendation JSONs to produce a deterministic recommendation
    that matches the JSON policy. Tolerant to minor schema drift.
    """
    def __init__(self, qa_path: str, rec_path: str):
        self.qa_path = qa_path
        self.rec_path = rec_path
        with open(qa_path, "r", encoding="utf-8") as f:
            self.qa = json.load(f)
        with open(rec_path, "r", encoding="utf-8") as f:
            self.rec = json.load(f)

        # Precompute
        self.flag_to_cat = self.rec.get("flag_to_category_mapping", {}) or {}
        self.scoring = self.rec.get("scoring", {}) or {}
        self.dep_logic = self.rec.get("dependence_flag_logic", {}) or {}
        self.final_thresholds = self.rec.get("final_decision_thresholds", {}) or {}
        self.final_rec = self.rec.get("final_recommendation", {}) or {}

        # Templates
        self.greetings = self.rec.get("greeting_templates") or ["Hi"]
        self.positive_states = self.rec.get("positive_state_templates") or ["doing well"]
        self.encouragements = self.rec.get("encouragement_templates") or ["We’re here if things change."]
        self.pref_templates = self.rec.get("preference_clause_templates") or {"default": ["Let’s find the best option."]}
        self.issue_phrases = self.rec.get("issue_phrases") or {}

        # Sanity defaults
        self.assisted_cut = 6
        self.inhome_cut = 3
        # Extract explicit thresholds if present
        # Values are textual; keep defaults above if parsing fails
        try:
            if "assisted_living" in self.final_thresholds:
                # e.g., "Recommend if assisted_living score >= 6"
                txt = self.final_thresholds["assisted_living"]
                self.assisted_cut = int(''.join(ch for ch in txt if ch.isdigit()))
        except Exception:
            pass
        try:
            if "in_home_with_support" in self.final_thresholds:
                txt = self.final_thresholds["in_home_with_support"]
                # try to capture the in_home >= N; default to 3
                digits = [int(''.join(filter(str.isdigit, token))) for token in txt.split() if any(ch.isdigit() for ch in token)]
                if digits:
                    self.inhome_cut = digits[0]
        except Exception:
            pass

    # ---------- Helpers ----------
    def _collect_flags(self, answers: Dict[str, int]) -> Dict[str, List[str]]:
        flags_by_cat: Dict[str, List[str]] = {}
        for i, q in enumerate(self.qa.get("questions", []), start=1):
            ans_val = int(answers.get(f"q{i}", -999))
            trig = q.get("trigger") or {}
            for cat, rules in trig.items():
                for rule in rules:
                    try:
                        if int(rule.get("answer", -999)) == ans_val:
                            fl = rule.get("flag")
                            if fl:
                                flags_by_cat.setdefault(cat, []).append(fl)
                    except Exception:
                        continue
        return flags_by_cat

    def _normalize_flags(self, flags: Set[str]) -> Set[str]:
        norm = set(flags)
        # historical synonyms (keep conservative so we don't mis-trigger)
        if "severe_cognitive_decline" in norm and "severe_cognitive_risk" not in norm:
            norm.add("severe_cognitive_risk")
        if "high_dependence" in norm or "high_mobility_dependence" in norm:
            norm.add("dependence_signal")
        return norm

    def _derive_flags(self, flags: Set[str]) -> Set[str]:
        out = set(flags)
        # Dependence derived if 2+ of configured triggers present
        dep_triggers = set(self.dep_logic.get("trigger_if_flags") or [])
        if dep_triggers:
            hits = len(dep_triggers.intersection(out))
            if hits >= 2:
                out.add("dependence")
        # Memory care required override per JSON: severe_cognitive_risk + no_support
        if {"severe_cognitive_risk", "no_support"}.issubset(out):
            out.add("memory_care_required")
        return out

    def _categories_present(self, flags_by_cat: Dict[str, List[str]]) -> Set[str]:
        # Build a normalized mapping based on flag_to_category_mapping
        present: Set[str] = set()
        for cat, flist in flags_by_cat.items():
            # If the QA used a category unmatched by scoring, remap using per-flag mapping
            for fl in flist:
                mapped = self.flag_to_cat.get(fl, cat)
                present.add(mapped)
        return present

    def _score(self, categories_present: Set[str]) -> Dict[str, int]:
        scores: Dict[str, int] = {}
        for scenario, weights in self.scoring.items():
            val = 0
            for cat in categories_present:
                if cat in weights:
                    try:
                        val += int(weights[cat])
                    except Exception:
                        continue
            scores[scenario] = val
        return scores

    def _pick_issue_phrases(self, flags: List[str], limit: int = 3) -> str:
        chosen = []
        for f in flags:
            phrases = self.issue_phrases.get(f)
            if phrases:
                chosen.append(phrases[0])
            if len(chosen) >= limit:
                break
        return ", ".join(chosen)

    def _pref_clause(self, flags: Set[str]) -> str:
        if "strongly_prefers_home" in flags:
            key = "strongly_prefers_home"
        elif "prefers_home" in flags:
            key = "prefers_home"
        elif "open_to_move" in flags:
            key = "open_to_move"
        else:
            key = "default"
        arr = self.pref_templates.get(key) or self.pref_templates.get("default") or ["Let's find a good fit."]
        return arr[0]

    def _greeting(self) -> str:
        return (self.greetings[0] if self.greetings else "Hi")

    def _positive_state(self) -> str:
        return (self.positive_states[0] if self.positive_states else "doing well")

    def _encouragement(self) -> str:
        return (self.encouragements[0] if self.encouragements else "We’re here if things change.")

    def _render(self, template_obj: dict, name: Optional[str], key_flags: List[str], care_label: str) -> str:
        if not template_obj:
            return ""
        template = template_obj.get("message_template") or template_obj.get("message") or ""
        if not template:
            return ""
        greeting = self._greeting()
        positive = self._positive_state()
        encouragement = self._encouragement()
        pref_clause = self._pref_clause(set(key_flags))
        key_issues = self._pick_issue_phrases(key_flags, limit=3)

        # Safe format
        def safe(s: str) -> str:
            return (s or "").replace("{", "{{").replace("}", "}}")

        fmt = template
        # Tolerant replace (we don't want KeyError)
        fmt = fmt.replace("{greeting}", greeting)
        fmt = fmt.replace("{name}", name or "there")
        fmt = fmt.replace("{positive_state}", positive)
        fmt = fmt.replace("{encouragement}", encouragement)
        fmt = fmt.replace("{recommendation}", care_label)
        fmt = fmt.replace("{preference_clause}", pref_clause)
        fmt = fmt.replace("{key_issues}", key_issues or "your current needs")

        return fmt

    def run(self, answers: Dict[str, int], conditional_answer: Optional[str] = None, name: Optional[str] = None) -> PlannerResult:
        # 1) Collect raw flags
        by_cat = self._collect_flags(answers)
        raw_flags: Set[str] = set(itertools.chain.from_iterable(by_cat.values()))

        # 2) Normalize and derive
        norm = self._normalize_flags(raw_flags)
        flags = self._derive_flags(norm)

        # 3) Category presence and scoring
        present = self._categories_present(by_cat)
        scores = self._score(present)
        al_score = int(scores.get("assisted_living", 0))
        ih_score = int(scores.get("in_home", 0))

        # 4) Decide care_type with strict overrides first
        care_type = "in_home"
        narrative_block: dict = {}
        reasons: List[str] = []

        # Hard override: memory care if severe cognitive + no support
        if "memory_care_required" in flags:
            care_type = "memory_care"
            narrative_block = self.final_rec.get("memory_care_override") or {}
        else:
            # Threshold logic
            if al_score >= self.assisted_cut:
                care_type = "assisted_living"
            elif ih_score >= self.inhome_cut and al_score < self.assisted_cut:
                care_type = "in_home"
            else:
                # No strong scores
                dep_triggers = set(self.dep_logic.get("trigger_if_flags") or [])
                has_dep = bool(dep_triggers.intersection(flags))
                if (ih_score < 3 and al_score < 3) and not has_dep:
                    care_type = "no_care_needed"
                else:
                    # fallback: lean safer
                    care_type = "assisted_living" if al_score >= ih_score else "in_home"

        # 5) Narrative selection guided by JSON
        fr = self.final_rec
        care_label = {
            "in_home": "in‑home care",
            "assisted_living": "assisted living",
            "memory_care": "memory care",
            "no_care_needed": "independent living with safety check‑ins"
        }.get(care_type, care_type.replace("_"," "))

        # choose best fitting message template
        if care_type == "memory_care":
            narrative_block = fr.get("memory_care_override") or narrative_block
        elif care_type == "assisted_living":
            # specialized variant if criteria fit
            cond = {"moderate_dependence", "moderate_mobility", "moderate_cognitive_decline"}
            if al_score >= self.assisted_cut and ih_score >= self.inhome_cut and cond.issubset(flags):
                narrative_block = fr.get("moderate_needs_assisted_living_recommendation") or fr.get("assisted_living")
            else:
                narrative_block = fr.get("assisted_living")
        elif care_type == "no_care_needed":
            narrative_block = fr.get("no_care_needed")
        else:
            # in-home nuanced paths
            if ("needs_financial_assistance" in flags) and (al_score < self.assisted_cut) and (ih_score >= self.inhome_cut):
                narrative_block = fr.get("in_home_with_support_and_financial_needs")
            elif ({"moderate_cognitive_decline","severe_cognitive_risk"} & flags) or ({"moderate_safety_concern","high_safety_concern"} & flags):
                narrative_block = fr.get("in_home_possible_with_cognitive_and_safety_risks")
            elif ("high_mobility_dependence" in flags) and ("severe_cognitive_risk" not in flags):
                narrative_block = fr.get("in_home_with_mobility_challenges")
            else:
                narrative_block = fr.get("in_home_with_support")

        # Build reasons list: transform flags into human hints using issue_phrases first entry
        for f in sorted(flags):
            if f in self.issue_phrases:
                reasons.append(self.issue_phrases[f][0])

        # Add optional warnings
        siw = self.rec.get("social_isolation_warning") or {}
        if any(f in flags for f in (siw.get("trigger_if_flags") or [])):
            msg = siw.get("message_template") or siw.get("message")
            if msg:
                reasons.append(self._render({"message_template": msg}, name, list(flags), care_label))

        cdw = self.rec.get("cognitive_decline_warning") or {}
        if any(f in flags for f in (cdw.get("trigger_if_flags") or [])):
            msg = cdw.get("message_template") or cdw.get("message")
            if msg:
                reasons.append(self._render({"message_template": msg}, name, list(flags), care_label))

        advisory = self._render(narrative_block or {}, name, list(flags), care_label)

        return PlannerResult(
            care_type=care_type,
            flags=flags,
            scores={"assisted_living": al_score, "in_home": ih_score},
            reasons=[r for r in reasons if r],
            advisory=advisory or None,
            message=advisory or None,
            message_rendered=advisory or None,
        )

class CalculatorEngine:
    """
    Minimal stable calculator. Uses hourly * hours * days for in-home,
    and base + adders for facility care. Multipliers optional.
    """
    def __init__(self, settings: Optional[dict]=None):
        # Sensible defaults; the Streamlit app may override these via JSON.
        self.settings = settings or {
            "state_multiplier": {"National": 1.0, "Washington": 1.08, "California": 1.15, "Texas": 0.98, "Florida": 1.02},
            "facility_base": {"Studio": 4200, "1 Bedroom": 5200, "Shared": 3800},
            "care_level_add": {"Low": 0, "Medium": 400, "High": 900},
            "mobility_add":   {"Independent": 0, "Assisted": 150, "Non-ambulatory": 350},
            "chronic_add":    {"None": 0, "Some": 150, "Multiple/Complex": 300},
            "memory_care_multiplier": 1.25,
            "in_home_hourly": 42,
            "days_per_month": 30,
        }

    def _state_mult(self, state: str) -> float:
        return float((self.settings.get("state_multiplier") or {}).get(state or "National", 1.0))

    def monthly_cost(self, inputs: Any) -> int:
        care_type = getattr(inputs, "care_type", "in_home")
        state = getattr(inputs, "state", "National")
        mult = self._state_mult(state)

        if care_type in ("assisted_living", "memory_care"):
            room = getattr(inputs, "room_type", "Studio")
            base = int((self.settings.get("facility_base") or {}).get(room, 4200))
            care = int((self.settings.get("care_level_add") or {}).get(getattr(inputs, "care_level","Medium"), 400))
            mob  = int((self.settings.get("mobility_add") or {}).get(getattr(inputs, "mobility","Independent"), 0))
            chrn = int((self.settings.get("chronic_add") or {}).get(getattr(inputs, "chronic","Some"), 150))
            total = base + care + mob + chrn
            if care_type == "memory_care":
                total = int(total * float(self.settings.get("memory_care_multiplier", 1.25)))
            return int(total * mult)

        # In-home
        hourly = float(self.settings.get("in_home_hourly", 42))
        hpd = int(getattr(inputs, "in_home_hours_per_day", 4))
        dpm = int(getattr(inputs, "in_home_days_per_month", 20))
        care = hourly * hpd * dpm
        mob  = int((self.settings.get("mobility_add") or {}).get(getattr(inputs, "mobility","Independent"), 0))
        chrn = int((self.settings.get("chronic_add") or {}).get(getattr(inputs, "chronic","Some"), 150))
        total = int(care) + mob + chrn
        return int(total * mult)

    # Backward-compat
    def estimate(self, care_type: str) -> int:
        class Dummy: pass
        d = Dummy()
        d.care_type = care_type
        d.state = "National"
        d.room_type = "Studio"
        d.care_level = "Medium"
        d.mobility = "Independent"
        d.chronic = "Some"
        d.in_home_hours_per_day = 4
        d.in_home_days_per_month = 20
        return self.monthly_cost(d)
