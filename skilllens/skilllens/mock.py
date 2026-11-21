"""A tiny simulated model so you can run SkillLens with no Ollama installed.

It follows the rules written in the unit-normalizer demo skill (so edits to the skill really
change its behavior) and picks causes with simple keyword scoring. It is for demos and tests ONLY:
results from it measure nothing about real models.
"""
from __future__ import annotations

import json
import re

_POS = ("love", "great", "thank", "amazing", "awesome", "perfect", "happy", "excellent")
_NEG = ("broken", "refund", "crash", "worst", "late", "terrible", "awful", "angry", "not working")


class MockLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.cache_hits = 0

    def complete(self, messages: list[dict], *, temperature: float, seed: int,
                 json_mode: bool = False) -> str:
        self.calls += 1
        if json_mode:
            user = next(m["content"] for m in messages if m["role"] == "user")
            if "test inputs" in user:
                return self._propose(user)
            return self._investigate(user)
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        return self._convert(system, user)

    # ---- pretend to be a model that follows the unit-normalizer skill ----
    def _sentiment(self, skill: str, user: str) -> str:
        low = user.lower()
        kind = ("positive" if any(w in low for w in _POS)
                else "negative" if any(w in low for w in _NEG) else "neutral")
        labels: dict[str, str] = {}
        for left, label in re.findall(r"^-\s*(.+?)\s*->\s*(positive|negative|neutral)", skill, re.M | re.I):
            l = left.lower()
            if re.search(r"praise|thanks|happ", l):
                labels["positive"] = label.lower()
            elif re.search(r"complain|anger|problem", l):
                labels["negative"] = label.lower()
            elif re.search(r"question|fact|feeling", l):
                labels["neutral"] = label.lower()
        out = labels.get(kind, "neutral")        # a missing rule means the model falls back to "neutral"
        if "lowercase" not in skill:
            out = out.capitalize() + "."
        if "exactly one word" not in skill:
            out = f"I think the message is {out}"
        return out

    def _convert(self, skill: str, user: str) -> str:
        m = re.match(r"\s*Convert\s+([\d.]+)\s+(\w+)", user)
        if not m:
            return self._sentiment(skill, user)
        value, unit = float(m.group(1)), m.group(2)
        rules = {u: (float(f), t) for u, f, t in
                 re.findall(r"\((\w+)\):\s*multiply by ([0-9.]+) to get (\w+)", skill)}
        body: dict
        if unit == "F" and re.search(r"\(F\):", skill):
            body = {"value": (value - 32) * 5 / 9 + 273.15, "unit": "K"}
        elif unit == "C" and re.search(r"\(C\):", skill):
            body = {"value": value + 273.15, "unit": "K"}
        elif unit in rules:
            factor, target = rules[unit]
            body = {"value": value * factor, "unit": target}
        elif "unsupported unit" in skill:
            body = {"error": "unsupported unit"}
        else:
            body = {"value": value, "unit": unit}
        if "value" in body and "Round the value" in skill:
            body["value"] = round(body["value"], 4)
        text = json.dumps(body)
        if "Return only the JSON" not in skill:
            text = "Sure! Here is the result:\n" + text
        return text

    # ---- pretend to write test inputs ----
    def _propose(self, user: str) -> str:
        if "Sentiment Labeler" in user:
            items = ["I love this app, thank you!", "Great support, very happy", "Awesome update, works perfectly",
                     "My parcel arrived broken, I want a refund", "The app crashes on startup", "Worst service ever",
                     "The delivery was late again", "What time do you open?", "I ordered on Friday.",
                     "How can I reset my email address?", "Terrible experience, I am angry", "Excellent quality"]
        elif "Unit Normalizer" in user:
            items = ["Convert 3 mi", "Convert 10 ft", "Convert 6 in", "Convert 5 lb", "Convert 8 oz",
                     "Convert 50 F", "Convert 20 C", "Convert 4 furlong"]
        else:
            items = ["Hello there", "Please help me", "What can you do?", "Short one", "Another question"]
        return json.dumps({"inputs": items})

    # ---- pretend to be an investigator: keyword scoring ----
    def _investigate(self, user: str) -> str:
        changes = re.findall(r"CHANGE (c\d+)\n  removed: (.*)\n  added: (.*)", user)
        units = set(re.findall(r"Input: Convert [\d.]+ (\w+)", user))
        failed = " ".join(re.findall(r"Failed checks \(new version\): (.*)", user))
        inputs = " ".join(re.findall(r"Input: (.*)", user)).lower()
        bad_outputs = re.findall(r"New output \(bad\): (.*)", user)
        scored = []
        for cid, removed, added in changes:
            text = f"{removed} {added}"
            score = sum(1 for u in units if f"({u})" in text)
            if any(w in inputs for w in _NEG) and re.search(r"complain|anger|problem", text, re.I):
                score += 3
            if any(w in inputs for w in _POS) and re.search(r"praise|thanks|happ", text, re.I):
                score += 3
            if any(re.search(r"[A-Z.]|\s", o.strip()) for o in bad_outputs) and re.search(r"lowercase|one word|punctuation", text, re.I):
                score += 3
            if "json_valid" in failed and "JSON" in text:
                score += 3
            if "json_field_equals" in failed and "unsupported" in text:
                score += 3
            scored.append((score, cid))
        scored.sort(key=lambda t: -t[0])
        top = [cid for s, cid in scored if s > 0][:2] or [changes[0][0]]
        by_id = {cid: (rem, add) for cid, rem, add in changes}

        def quote(cid: str) -> str:
            rem, add = by_id[cid]
            return (add if rem == "(nothing)" else rem)[:40]

        causes = [{"change_ids": [cid], "quote": quote(cid),
                   "description": f"Mock analysis: change {cid} best matches the failures.",
                   "confidence": "medium"} for cid in top]
        return json.dumps({"causes": causes})
