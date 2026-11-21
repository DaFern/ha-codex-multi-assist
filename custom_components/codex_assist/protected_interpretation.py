"""Shared conversational interpretation policy, independent of action authority."""

import re

INTERPRETATION_INSTRUCTIONS = (
    "Understand ordinary speech across every supplied non-security capability, not "
    "just exact command phrases. Interpret small transcription errors, missing filler "
    "words, synonyms, singular/plural and near-matching names using the permitted "
    "reference catalogue and recent conversation. Do not demand verbatim entity names. "
    "The latest user's correction overrides an earlier mistaken interpretation; "
    "'no, off', 'the other one', 'same room' and similar short replies refer to the "
    "recent task when that reference is clear. Do not repeat an earlier completed action. "
    "Preserve the intended direction: never change off into on, pause into resume, "
    "or lower into higher because of old dialogue or the current device state. "
    "Current states help explain results; they do not prove what the user intended. "
    "Do not treat a request for a state already set as an opposite/toggle request. "
    "Use room names and aliases to select matching permitted entities. An ordinary "
    "request for a room's lights excludes displays, backlights and status indicators "
    "unless the user asks for them. A group reference lists exact direct members: "
    "use those member IDs, never call a group, invent IDs or infer access to omitted "
    "members. If an exact group is absent, resolve from the permitted room/category "
    "catalogue without claiming it is the complete hidden group. Keep distinct "
    "requests and different speakers' references separate when the topic changes. "
    "If one interpretation is clearly supported, act rather than repeatedly asking "
    "the same question. If a missing or contradictory word leaves materially different "
    "actions plausible, ask one short question naming the alternatives; do not guess. "
    "A question about state is not itself an instruction to change state. Never "
    "fabricate missing numeric levels; use supplied relative actions for relative requests. Never "
    "infer a security-sensitive action, permission, speaker identity or unsupported "
    "capability. Recognition evidence and action authorisation remain independent."
)


def resolve_reference(value, catalogue, domains):
    """Resolve only a unique exact permitted alias; fuzzy inference stays with the model."""
    if type(value) is not str:
        return None
    query = " ".join(value.casefold().split())
    direct = [
        row["entity_id"] for row in catalogue
        if row["entity_id"].partition(".")[0] in domains and row["entity_id"].casefold() == query
    ]
    if len(direct) == 1:
        return direct[0]
    matches = {
        row["entity_id"] for row in catalogue
        if row["entity_id"].partition(".")[0] in domains
        and any(
            query == " ".join(label.casefold().split())
            for label in (row["entity_id"], row["name"], *row.get("aliases", []))
        )
    }
    return next(iter(matches)) if len(matches) == 1 else None


def explicit_direction_conflict(text, name, arguments):
    """Catch unambiguous latest-direction contradictions before any batch effect.

    This is a veto/replanning hint, not an intent parser, typo corrector or a grant.
    Ambiguous/mixed/negated wording stays with the model's clarification policy.
    """
    words = re.findall(r"[a-z]+", str(text).casefold().replace("’", "'"))
    joined = " ".join(words)
    if re.search(r"\b(?:not|never|don t|dont|do not)\b", joined):
        return None
    if name == "codex_assist__ordinary_devices":
        action = arguments.get("action")
        if action in {"turn_on", "turn_off", "power_on", "power_off", "set_light", "set_fan_speed"}:
            operation = (
                "turn_off" if action in {"turn_off", "power_off"}
                or (action in {"set_light", "set_fan_speed"} and arguments.get("level") == 0)
                else "turn_on"
            )
            return explicit_direction_conflict(
                text, "codex_assist__guest_on_off", {"operation": operation},
            )
        if action in {"open_blind", "close_blind", "stop_blind"}:
            direction = set(words) & {"open", "close", "stop"}
            if len(direction) == 1 and action != next(iter(direction)) + "_blind":
                return "The proposed blind action contradicts the latest explicit direction."
            return None
        return explicit_direction_conflict(text, "codex_assist__guest_music", arguments)
    if name == "codex_assist__guest_on_off":
        directions = set(words) & {"on", "off"}
        if len(directions) != 1:
            return None
        if not (
            set(words) & {"turn", "switch", "shut"}
            or re.fullmatch(
                r"(?:(?:no|please|them|it|actually)\s+)*(?:on|off)(?:\s+please)?", joined,
            )
        ):
            return None
        wanted = "turn_" + next(iter(directions))
        if arguments.get("operation") != wanted:
            return f"The latest request explicitly says {wanted}; do not propose the opposite."
    elif name == "codex_assist__guest_music":
        pairs = (
            ({"pause"}, {"resume"}, "pause", "resume"),
            ({"quieter", "lower", "down"}, {"louder", "higher", "up"}, "volume_down", "volume_up"),
            ({"previous"}, {"next"}, "previous", "next"),
        )
        for first, second, first_action, second_action in pairs:
            left, right = bool(set(words) & first), bool(set(words) & second)
            if left == right:
                continue
            wanted, opposite = (
                (first_action, second_action) if left else (second_action, first_action)
            )
            if arguments.get("action") == opposite:
                return f"The latest request says {wanted}, not {opposite}."
    return None
