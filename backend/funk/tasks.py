"""The SRC radio tasks the trainer can set.

Each task is one of the spoken procedures from the practical part of the
German Short Range Certificate exam: the candidate reads a German situation
("Lage") and has to transmit the matching English VHF message. `reference` is
the textbook message the grader compares against; `checklist` names the
elements that must be present, in order, and is what the grader scores. Both
are withheld from GET /api/funk and only returned with an evaluation, so the
candidate can't read the answer off the task list.

Formats follow the usual SRC teaching material (DSC alert first, then the
voice message on channel 16). Where valid variants exist (e.g. MMSI before or
after the call sign) the grader is told to accept them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Ship:
    name: str
    call_sign: str  # as written, e.g. "DG7123"
    call_sign_spoken: str  # NATO/ITU spelling, e.g. "Delta Golf Seven One Two Three"
    mmsi: str


@dataclass(frozen=True)
class FunkTask:
    id: str
    category: str  # Notverkehr | Dringlichkeitsverkehr | Sicherheitsverkehr | Routineverkehr
    title: str
    situation: str  # German "Lage", shown to the candidate
    own_ship: Ship
    reference: str  # the textbook English message
    checklist: list[str] = field(default_factory=list)
    other_ship: Ship | None = None

    def public(self) -> dict:
        """What the candidate sees before transmitting — no reference, no
        checklist, and no ready-made spelling of the call sign (spelling it
        is part of the exercise)."""
        data = {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "situation": self.situation,
            "own_ship": _public_ship(self.own_ship),
        }
        if self.other_ship:
            data["other_ship"] = _public_ship(self.other_ship)
        return data


def _public_ship(ship: Ship) -> dict:
    data = asdict(ship)
    data.pop("call_sign_spoken")
    return data


SEESCHWALBE = Ship("Seeschwalbe", "DG7123", "Delta Golf Seven One Two Three", "211239680")
HAITHABU = Ship("Haithabu", "DK4521", "Delta Kilo Four Five Two One", "211457230")
MOEWE = Ship("Möwe", "DH2876", "Delta Hotel Two Eight Seven Six", "211876540")
KRISTINA = Ship("Kristina", "DB3309", "Delta Bravo Three Three Zero Nine", "211330950")


TASKS: list[FunkTask] = [
    FunkTask(
        id="mayday-feuer",
        category="Notverkehr",
        title="Notmeldung: Feuer an Bord",
        situation=(
            "Sie sind Skipper der Segelyacht SEESCHWALBE. Position 54°32'N 010°17'E. "
            "Im Motorraum ist ein Feuer ausgebrochen, das Sie nicht unter Kontrolle bekommen. "
            "Sie benötigen sofortige Hilfe. 4 Personen an Bord, Sie bereiten das Verlassen "
            "des Schiffes in die Rettungsinsel vor. Der DSC-Notalarm wurde bereits ausgelöst. "
            "Geben Sie die Notmeldung auf Kanal 16 ab."
        ),
        own_ship=SEESCHWALBE,
        reference=(
            "MAYDAY MAYDAY MAYDAY\n"
            "THIS IS\n"
            "SEESCHWALBE SEESCHWALBE SEESCHWALBE\n"
            "Delta Golf Seven One Two Three\n"
            "MMSI 211239680\n"
            "MAYDAY\n"
            "SEESCHWALBE, Delta Golf Seven One Two Three, MMSI 211239680\n"
            "POSITION five four degrees three two minutes north, zero one zero degrees one seven minutes east\n"
            "I AM ON FIRE\n"
            "I REQUIRE IMMEDIATE ASSISTANCE\n"
            "FOUR PERSONS ON BOARD, PREPARING TO ABANDON VESSEL INTO LIFERAFT\n"
            "OVER"
        ),
        checklist=[
            "Notzeichen MAYDAY dreimal",
            "THIS IS",
            "Schiffsname dreimal",
            "Rufzeichen mit Buchstabieralphabet",
            "MMSI",
            "MAYDAY einmal, dann Name, Rufzeichen, MMSI einmal",
            "POSITION (Breite und Länge korrekt)",
            "Art der Not: Feuer (I AM ON FIRE)",
            "Art der Hilfe: I REQUIRE IMMEDIATE ASSISTANCE",
            "Weitere Angaben: 4 Personen, Verlassen des Schiffes",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="mayday-wassereinbruch",
        category="Notverkehr",
        title="Notmeldung: Wassereinbruch, Schiff sinkt",
        situation=(
            "Sie sind Skipper der Motoryacht HAITHABU. Position 55°04'N 011°52'E. "
            "Nach einer Grundberührung haben Sie starken Wassereinbruch, die Lenzpumpen schaffen "
            "es nicht, die Yacht sinkt. 3 Personen an Bord, alle tragen Rettungswesten. "
            "Der DSC-Notalarm wurde bereits ausgelöst. Geben Sie die Notmeldung auf Kanal 16 ab."
        ),
        own_ship=HAITHABU,
        reference=(
            "MAYDAY MAYDAY MAYDAY\n"
            "THIS IS\n"
            "HAITHABU HAITHABU HAITHABU\n"
            "Delta Kilo Four Five Two One\n"
            "MMSI 211457230\n"
            "MAYDAY\n"
            "HAITHABU, Delta Kilo Four Five Two One, MMSI 211457230\n"
            "POSITION five five degrees zero four minutes north, zero one one degrees five two minutes east\n"
            "I AM SINKING AFTER GROUNDING\n"
            "I REQUIRE IMMEDIATE ASSISTANCE\n"
            "THREE PERSONS ON BOARD, ALL WEARING LIFEJACKETS\n"
            "OVER"
        ),
        checklist=[
            "Notzeichen MAYDAY dreimal",
            "THIS IS",
            "Schiffsname dreimal",
            "Rufzeichen mit Buchstabieralphabet",
            "MMSI",
            "MAYDAY einmal, dann Name, Rufzeichen, MMSI einmal",
            "POSITION (Breite und Länge korrekt)",
            "Art der Not: sinkend / Wassereinbruch",
            "Art der Hilfe: I REQUIRE IMMEDIATE ASSISTANCE",
            "Weitere Angaben: 3 Personen, Rettungswesten",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="mayday-relay",
        category="Notverkehr",
        title="Weiterleitung einer Notmeldung (MAYDAY RELAY)",
        situation=(
            "Sie sind Skipper der Segelyacht MÖWE. Sie hören auf Kanal 16 eine schwache Notmeldung "
            "der Yacht KRISTINA: Position 54°28'N 010°39'E, Mastbruch und Kollision mit einem "
            "Wrackteil, Wassereinbruch, 2 Personen an Bord, sofortige Hilfe benötigt. "
            "Niemand bestätigt die Notmeldung, Sie selbst können nicht helfen. "
            "Leiten Sie die Notmeldung an alle Funkstellen weiter."
        ),
        own_ship=MOEWE,
        other_ship=KRISTINA,
        reference=(
            "MAYDAY RELAY MAYDAY RELAY MAYDAY RELAY\n"
            "ALL STATIONS ALL STATIONS ALL STATIONS\n"
            "THIS IS\n"
            "MOEWE MOEWE MOEWE\n"
            "Delta Hotel Two Eight Seven Six\n"
            "MMSI 211876540\n"
            "RECEIVED FOLLOWING MAYDAY FROM KRISTINA, Delta Bravo Three Three Zero Nine, MMSI 211330950\n"
            "MAYDAY\n"
            "KRISTINA, Delta Bravo Three Three Zero Nine, MMSI 211330950\n"
            "POSITION five four degrees two eight minutes north, zero one zero degrees three nine minutes east\n"
            "DISMASTED AND COLLISION WITH WRECKAGE, TAKING WATER\n"
            "REQUIRES IMMEDIATE ASSISTANCE\n"
            "TWO PERSONS ON BOARD\n"
            "OVER"
        ),
        checklist=[
            "MAYDAY RELAY dreimal",
            "ALL STATIONS dreimal",
            "THIS IS, eigener Name dreimal",
            "Eigenes Rufzeichen mit Buchstabieralphabet und MMSI",
            "Hinweis auf empfangene Notmeldung (RECEIVED FOLLOWING MAYDAY FROM ...)",
            "MAYDAY, Name/Kennung des Havaristen KRISTINA",
            "POSITION des Havaristen (korrekt)",
            "Art der Not des Havaristen",
            "Benötigte Hilfe (REQUIRES IMMEDIATE ASSISTANCE)",
            "Weitere Angaben: 2 Personen",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="mayday-bestaetigung",
        category="Notverkehr",
        title="Bestätigung einer Notmeldung",
        situation=(
            "Sie sind Skipper der Segelyacht MÖWE. Sie empfangen die Notmeldung der Motoryacht "
            "HAITHABU (Rufzeichen DK4521, MMSI 211457230), die in Ihrer Nähe sinkt. "
            "Keine Küstenfunkstelle hat bestätigt. Sie können in 20 Minuten vor Ort sein. "
            "Bestätigen Sie den Empfang der Notmeldung per Sprechfunk auf Kanal 16 "
            "und teilen Sie mit, dass Sie in 20 Minuten eintreffen."
        ),
        own_ship=MOEWE,
        other_ship=HAITHABU,
        reference=(
            "MAYDAY\n"
            "HAITHABU HAITHABU HAITHABU\n"
            "Delta Kilo Four Five Two One\n"
            "MMSI 211457230\n"
            "THIS IS\n"
            "MOEWE MOEWE MOEWE\n"
            "Delta Hotel Two Eight Seven Six\n"
            "MMSI 211876540\n"
            "RECEIVED MAYDAY\n"
            "I AM PROCEEDING TO YOUR POSITION, ETA TWO ZERO MINUTES\n"
            "OVER"
        ),
        checklist=[
            "MAYDAY einmal",
            "Name des Havaristen dreimal (oder Rufzeichen/MMSI)",
            "Kennung des Havaristen (Rufzeichen/MMSI)",
            "THIS IS, eigener Name dreimal",
            "Eigenes Rufzeichen mit Buchstabieralphabet und MMSI",
            "RECEIVED MAYDAY",
            "Angabe der Hilfe: unterwegs, ETA 20 Minuten",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="fehlalarm",
        category="Notverkehr",
        title="Aufhebung eines versehentlichen DSC-Notalarms",
        situation=(
            "Sie sind Skipper der Segelyacht SEESCHWALBE, Position 54°21'N 010°09'E. "
            "Heute um 14:35 UTC wurde versehentlich ein DSC-Notalarm ausgelöst. "
            "Es besteht keine Notlage. Heben Sie den Fehlalarm per Sprechfunk auf Kanal 16 auf."
        ),
        own_ship=SEESCHWALBE,
        reference=(
            "ALL STATIONS ALL STATIONS ALL STATIONS\n"
            "THIS IS\n"
            "SEESCHWALBE SEESCHWALBE SEESCHWALBE\n"
            "Delta Golf Seven One Two Three\n"
            "MMSI 211239680\n"
            "POSITION five four degrees two one minutes north, zero one zero degrees zero nine minutes east\n"
            "CANCEL MY DISTRESS ALERT OF TODAY AT one four three five UTC\n"
            "OVER"
        ),
        checklist=[
            "ALL STATIONS dreimal",
            "THIS IS, Name dreimal",
            "Rufzeichen mit Buchstabieralphabet und MMSI",
            "POSITION (korrekt)",
            "CANCEL MY DISTRESS ALERT OF ... (Datum/Zeit 14:35 UTC)",
            "Kein MAYDAY verwendet",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="panpan-motorausfall",
        category="Dringlichkeitsverkehr",
        title="Dringlichkeitsmeldung: Motorausfall im Fahrwasser",
        situation=(
            "Sie sind Skipper der Motoryacht HAITHABU, Position 54°25'N 010°12'E, im Fahrwasser "
            "der Kieler Förde. Ihr Motor ist ausgefallen, Sie treiben manövrierunfähig. Keine "
            "unmittelbare Gefahr für Leib und Leben, aber Sie benötigen Schlepphilfe. "
            "2 Personen an Bord. Geben Sie eine Dringlichkeitsmeldung an alle Funkstellen ab."
        ),
        own_ship=HAITHABU,
        reference=(
            "PAN PAN PAN PAN PAN PAN\n"
            "ALL STATIONS ALL STATIONS ALL STATIONS\n"
            "THIS IS\n"
            "HAITHABU HAITHABU HAITHABU\n"
            "Delta Kilo Four Five Two One\n"
            "MMSI 211457230\n"
            "POSITION five four degrees two five minutes north, zero one zero degrees one two minutes east\n"
            "ENGINE FAILURE, I AM NOT UNDER COMMAND AND DRIFTING IN THE FAIRWAY\n"
            "I REQUIRE TOW ASSISTANCE\n"
            "TWO PERSONS ON BOARD\n"
            "OVER"
        ),
        checklist=[
            "PAN PAN dreimal",
            "ALL STATIONS dreimal",
            "THIS IS, Name dreimal",
            "Rufzeichen mit Buchstabieralphabet und MMSI",
            "POSITION (korrekt)",
            "Art des Problems: Motorausfall, manövrierunfähig, treibend",
            "Benötigte Hilfe: Schlepphilfe",
            "Weitere Angaben: 2 Personen",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="panpan-medico",
        category="Dringlichkeitsverkehr",
        title="Dringlichkeitsmeldung: Verletztes Crewmitglied",
        situation=(
            "Sie sind Skipper der Segelyacht KRISTINA, Position 54°45'N 010°48'E. Ein Crewmitglied "
            "ist beim Sturz schwer am Kopf verletzt worden und zeitweise bewusstlos. "
            "Sie benötigen medizinische Beratung. Rufen Sie mit einer Dringlichkeitsmeldung "
            "die Seenotleitung BREMEN RESCUE an."
        ),
        own_ship=KRISTINA,
        reference=(
            "PAN PAN PAN PAN PAN PAN\n"
            "BREMEN RESCUE BREMEN RESCUE BREMEN RESCUE\n"
            "THIS IS\n"
            "KRISTINA KRISTINA KRISTINA\n"
            "Delta Bravo Three Three Zero Nine\n"
            "MMSI 211330950\n"
            "POSITION five four degrees four five minutes north, zero one zero degrees four eight minutes east\n"
            "ONE CREW MEMBER SERIOUSLY INJURED AT THE HEAD, TEMPORARILY UNCONSCIOUS\n"
            "I REQUIRE MEDICAL ADVICE\n"
            "OVER"
        ),
        checklist=[
            "PAN PAN dreimal",
            "BREMEN RESCUE dreimal (gerufene Stelle)",
            "THIS IS, Name dreimal",
            "Rufzeichen mit Buchstabieralphabet und MMSI",
            "POSITION (korrekt)",
            "Art des Problems: Kopfverletzung, zeitweise bewusstlos",
            "Benötigte Hilfe: MEDICAL ADVICE",
            "Abschluss OVER",
        ],
    ),
    FunkTask(
        id="securite-container",
        category="Sicherheitsverkehr",
        title="Sicherheitsmeldung: Treibender Container",
        situation=(
            "Sie sind Skipper der Segelyacht MÖWE. Sie sichten in Position 54°36'N 010°25'E "
            "einen treibenden, halb getauchten Container, eine Gefahr für die Schifffahrt. "
            "Geben Sie eine Sicherheitsmeldung an alle Funkstellen ab."
        ),
        own_ship=MOEWE,
        reference=(
            "SECURITE SECURITE SECURITE\n"
            "ALL STATIONS ALL STATIONS ALL STATIONS\n"
            "THIS IS\n"
            "MOEWE MOEWE MOEWE\n"
            "Delta Hotel Two Eight Seven Six\n"
            "MMSI 211876540\n"
            "DRIFTING CONTAINER, PARTLY SUBMERGED,\n"
            "IN POSITION five four degrees three six minutes north, zero one zero degrees two five minutes east\n"
            "DANGEROUS TO NAVIGATION\n"
            "OUT"
        ),
        checklist=[
            "SECURITE dreimal",
            "ALL STATIONS dreimal",
            "THIS IS, Name dreimal",
            "Rufzeichen mit Buchstabieralphabet und MMSI",
            "Art der Gefahr: treibender, halb getauchter Container",
            "POSITION der Gefahr (korrekt)",
            "Hinweis DANGEROUS TO NAVIGATION",
            "Abschluss OUT",
        ],
    ),
    FunkTask(
        id="routine-hafen",
        category="Routineverkehr",
        title="Routineanruf an eine Küstenfunkstelle",
        situation=(
            "Sie sind Skipper der Segelyacht SEESCHWALBE und möchten die Verkehrszentrale "
            "KIEL TRAFFIC auf Kanal 22 anrufen, um nach der Verkehrslage in der Kieler Förde "
            "zu fragen. Führen Sie den Anruf durch."
        ),
        own_ship=SEESCHWALBE,
        reference=(
            "KIEL TRAFFIC KIEL TRAFFIC KIEL TRAFFIC\n"
            "THIS IS\n"
            "SEESCHWALBE SEESCHWALBE SEESCHWALBE\n"
            "Delta Golf Seven One Two Three\n"
            "REQUEST TRAFFIC INFORMATION FOR KIEL FJORD\n"
            "OVER"
        ),
        checklist=[
            "Gerufene Stelle KIEL TRAFFIC (bis zu dreimal)",
            "THIS IS",
            "Eigener Name (bis zu dreimal)",
            "Rufzeichen mit Buchstabieralphabet",
            "Anliegen: Anfrage Verkehrslage",
            "Kein Not-/Dringlichkeits-/Sicherheitszeichen",
            "Abschluss OVER",
        ],
    ),
]

_BY_ID = {task.id: task for task in TASKS}


def get_task(task_id: str) -> FunkTask | None:
    return _BY_ID.get(task_id)
