"""Hypothesis generation: the seam another team's generator plugs into.

`HypothesisGenerator.generate(grounding) -> list[Hypothesis]` is the whole
contract. Ours is `adapters.ClaudeHypothesisGenerator`; a replacement only has
to return `Hypothesis` objects aimed at `grounding.weak_premises`. Whatever
generates them, `select()` applies the same deterministic testability filter
and attaches the evidence context, so a scientist gets one interventional
claim per weak link, in the graph's own terms, with an experiment and a
falsification criterion attached — never a paragraph.

The frame follows the worked example in docs/reference: the hypothesis is the
weakest causal link restated as a prediction ("restoring X in aged human
cells will restore Y"), why it exists is the established links above it,
what conflicts is the contested ones, and what is missing is the recorded
absence. There is little creative room by design.
"""

from __future__ import annotations

from typing import Protocol

from backend.grounding.domain import Grounding, Hypothesis, Premise, PremiseStatus, premise_id

MAX_WORDS = 20
# A hypothesis with one of these is two claims wearing one sentence.
COMPOUND = (" and ", " but ", " even if ", " whereas ", " although ", " unless ", " or ", ";")


class HypothesisGenerator(Protocol):
    def generate(self, grounding: Grounding) -> list[Hypothesis]: ...


def testable(hypothesis: Hypothesis, grounding: Grounding) -> str | None:
    """None if it passes, else the one reason it does not."""
    premises = {premise_id(p): p for p in grounding.premises}
    target = premises.get(hypothesis.targets)
    if target is None:
        return "targets no known premise"
    if target.status is PremiseStatus.ESTABLISHED:
        return "targets an established link"
    if len(hypothesis.statement.split()) > MAX_WORDS:
        return f"statement longer than {MAX_WORDS} words"
    padded = f" {hypothesis.statement.lower()} "
    if any(marker in padded for marker in COMPOUND):
        return "compound claim"
    if (hypothesis.subject.lower(), hypothesis.object.lower()) != (target.subject.lower(), target.object.lower()):
        return "does not keep the target link's subject and object"
    if not (hypothesis.intervention and hypothesis.readout and hypothesis.model_system):
        return "missing intervention, readout or model system"
    if not hypothesis.falsification:
        return "missing falsification criterion"
    return None


def _adjacent(target: Premise, premises: list[Premise], status: PremiseStatus) -> list[str]:
    """Premises of `status` sharing a node with the target — its chain neighbours."""
    ends = {target.subject.lower(), target.object.lower()}
    return [
        premise_id(p)
        for p in premises
        if p.status is status and p is not target and ends & {p.subject.lower(), p.object.lower()}
    ]


def select(candidates: list[Hypothesis], grounding: Grounding) -> tuple[list[Hypothesis], list[tuple[Hypothesis, str]]]:
    """Filter, one per weak link, number, attach evidence context.
    Same candidates in -> same hypotheses out."""
    premises = {premise_id(p): p for p in grounding.premises}
    kept: list[Hypothesis] = []
    dropped: list[tuple[Hypothesis, str]] = []
    covered: set[str] = set()
    for candidate in candidates:
        reason = testable(candidate, grounding)
        if reason is None and candidate.targets in covered:
            reason = "second hypothesis for the same link"
        if reason is not None:
            dropped.append((candidate, reason))
            continue
        covered.add(candidate.targets)
        target = premises[candidate.targets]
        kept.append(
            candidate.model_copy(
                update={
                    "id": f"H{len(kept) + 1}",
                    "supported_by": _adjacent(target, grounding.premises, PremiseStatus.ESTABLISHED),
                    "conflicts_with": _adjacent(target, grounding.premises, PremiseStatus.CONTESTED),
                    "missing": target.absence_checked,
                }
            )
        )
    return kept, dropped
