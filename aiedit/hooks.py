"""Original hook patterns and user-supplied performance history; no invented viral claims."""

import json
import re
import threading
import time
import uuid
from pathlib import Path

PATTERNS = [
    {
        "id": "method",
        "template": "Here is how I {topic}.",
        "purpose": "Explain a specific method",
    },
    {
        "id": "mistake",
        "template": "The mistake I made with {topic}.",
        "purpose": "Show a real mistake and correction",
    },
    {
        "id": "before-after",
        "template": "What changed when I tried {topic}.",
        "purpose": "Compare a documented before and after",
    },
    {
        "id": "demo",
        "template": "Let me show you {topic}.",
        "purpose": "Lead with an actual demonstration",
    },
    {
        "id": "lesson",
        "template": "What I learned about {topic}.",
        "purpose": "Share a personal lesson",
    },
    {
        "id": "question",
        "template": "What happens when you try {topic}?",
        "purpose": "Answer a question with evidence",
    },
    {
        "id": "steps",
        "template": "My process for {topic}, step by step.",
        "purpose": "Explain a repeatable process",
    },
    {
        "id": "tradeoff",
        "template": "The trade-off behind {topic}.",
        "purpose": "Explain a concrete decision",
    },
]


class HookLibrary:
    def __init__(self, root):
        self.path = Path(root) / "hooks.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def entries(self):
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def add(self, entry):
        with self.lock:
            entries = self.entries()
            value = dict(entry, id=uuid.uuid4().hex[:12], created_at=time.time())
            entries.append(value)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
            temp.replace(self.path)
            return value

    def suggest(self, topic):
        terms = set(re.findall(r"\w+", topic.casefold()))
        history = self.entries()

        def relevance(entry):
            words = set(
                re.findall(r"\w+", (entry["topic"] + " " + entry["text"]).casefold())
            )
            return len(terms & words) / max(1, len(terms | words))

        ranked = sorted(
            history,
            key=lambda e: (relevance(e), e.get("retention") or 0, e.get("views") or 0),
            reverse=True,
        )
        return {
            "patterns": [
                dict(p, text=p["template"].format(topic=topic or "this process"))
                for p in PATTERNS
            ],
            "related_performance": [e for e in ranked if relevance(e) > 0][:5],
        }
