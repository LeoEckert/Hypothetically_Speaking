"""Grades a spoken SRC radio message with one LLM call.

The transcript comes from the browser's speech recognition, so it carries
ASR artefacts ("may day", "pan-pan", digits written as numerals, "securitay").
The prompt tells the grader to judge what was *said*, not how the recognizer
spelled it, and to grade against the task's checklist rather than demanding a
word-for-word match with the reference.
"""
from __future__ import annotations

import json
import re

from backend.funk.tasks import FunkTask

MAX_TRANSCRIPT_CHARS = 4000
STATUSES = ("ok", "fehlerhaft", "fehlt")


def build_prompt(task: FunkTask, transcript: str) -> str:
    own = task.own_ship
    other = task.other_ship
    other_line = (
        f"- Anderes Schiff: {other.name}, Rufzeichen {other.call_sign} ({other.call_sign_spoken}), MMSI {other.mmsi}\n"
        if other
        else ""
    )
    checklist = "\n".join(f"{i}. {item}" for i, item in enumerate(task.checklist, 1))
    return f"""Du bist Prüfer für das Short Range Certificate (SRC), den deutschen UKW-Seefunkschein.
Ein Prüfling hat die folgende Funkaufgabe gesprochen. Bewerte, ob er sie korrekt abgewickelt hat.

## Aufgabe: {task.title} ({task.category})
{task.situation}

- Eigenes Schiff: {own.name}, Rufzeichen {own.call_sign} ({own.call_sign_spoken}), MMSI {own.mmsi}
{other_line}
## Musterlösung
{task.reference}

## Prüfpunkte (in dieser Reihenfolge erwartet)
{checklist}

## Transkript des Prüflings
Das Transkript stammt aus automatischer Spracherkennung. Werte Erkennungsartefakte NICHT als Fehler:
"may day"/"mayday", "pan-pan"/"pan pan", "securitay"/"say cure it tay"/"security" für SECURITE,
Zahlen als Ziffern statt ausgeschriebener Wörter, fehlende Satzzeichen, Groß-/Kleinschreibung,
"Möwe"/"Moewe". Beurteile, was der Prüfling offensichtlich gesagt hat.
Echte Fehler sind dagegen: falsches oder fehlendes Verfahrenszeichen, falsche Anzahl der
Wiederholungen, fehlendes oder nicht buchstabiertes Rufzeichen (Rufzeichen muss mit dem
internationalen Buchstabieralphabet gesprochen werden, z.B. "Delta Golf"), falsche oder fehlende
Position, falsche Zahlen, fehlende Art der Not/Hilfe, falsche Reihenfolge, falscher Abschluss
(OVER vs. OUT), deutsche statt englischer Formulierungen.
Gleichwertige gängige Varianten (z.B. MMSI vor dem Rufzeichen, leicht andere englische
Formulierung mit gleichem Inhalt) sind korrekt.

\"\"\"
{transcript}
\"\"\"

## Bewertung
Prüfe jeden Prüfpunkt einzeln. Status: "ok", "fehlerhaft" (vorhanden, aber falsch) oder "fehlt".
Bestanden ist die Aufgabe nur, wenn Verfahrenszeichen, eigene Identifikation, Position (falls in
der Aufgabe gefordert) und der Kern der Meldung (Art der Not/Gefahr/des Anliegens) korrekt sind.
Kleinere Formfehler (z.B. Name nur zweimal statt dreimal) kosten Punkte, führen allein aber nicht
zum Durchfallen.

Antworte AUSSCHLIESSLICH mit einem ```json Codeblock in genau dieser Form, Texte auf Deutsch:

```json
{{
  "checklist": [
    {{"item": "<Prüfpunkt wörtlich wie oben>", "status": "ok|fehlerhaft|fehlt", "comment": "<kurz, was genau gesagt wurde oder fehlt>"}}
  ],
  "score": <0-100>,
  "passed": <true|false>,
  "summary": "<2-3 Sätze Gesamteindruck>",
  "tips": ["<konkreter Verbesserungshinweis>"]
}}
```"""


def _extract_json(text: str) -> dict | None:
    """The fenced block if there is one, else the outermost braces. Never raises."""
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize(payload: dict, task: FunkTask) -> dict:
    """Coerce the model's answer into a shape the frontend can render without
    guarding every field."""
    checklist = []
    for entry in payload.get("checklist") or []:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip().lower()
        checklist.append(
            {
                "item": str(entry.get("item", "")).strip(),
                "status": status if status in STATUSES else "fehlerhaft",
                "comment": str(entry.get("comment", "")).strip(),
            }
        )
    try:
        score = max(0, min(100, int(round(float(payload.get("score", 0))))))
    except (TypeError, ValueError):
        score = 0
    tips = [str(t).strip() for t in payload.get("tips") or [] if str(t).strip()]
    return {
        "task_id": task.id,
        "score": score,
        "passed": bool(payload.get("passed", False)),
        "summary": str(payload.get("summary", "")).strip(),
        "checklist": checklist,
        "tips": tips,
        "reference": task.reference,
    }


def grade(task: FunkTask, transcript: str, provider) -> dict:
    """Raises ValueError for an empty transcript or an unparseable answer;
    provider errors propagate for the caller to map to an HTTP status."""
    transcript = transcript.strip()
    if not transcript:
        raise ValueError("Das Transkript ist leer — bitte zuerst die Meldung sprechen.")
    transcript = transcript[:MAX_TRANSCRIPT_CHARS]
    response = provider.complete(build_prompt(task, transcript), max_tokens=2000)
    payload = _extract_json(response.text or "")
    if payload is None:
        raise ValueError("Die Bewertung des Modells war nicht lesbar — bitte erneut versuchen.")
    result = _normalize(payload, task)
    result["model"] = response.model or getattr(provider, "model", "")
    return result
