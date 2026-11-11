import json
import os
import urllib.error
import urllib.request


WOLF = "werewolf"
VILLAGER = "villager"
SEER = "seer"
DOCTOR = "doctor"

ROLE_KEYS = (
    "role", "your_role", "my_role", "player_role", "self_role", "role_name",
    "character", "alignment", "faction",
)
SEAT_KEYS = (
    "seat", "my_seat", "player_seat", "self_seat", "your_seat", "id",
    "player_id", "number", "index", "position",
)
ACTOR_KEYS = (
    "actor", "speaker", "voter", "source", "from", "by", "seat", "player",
    "who", "accuser", "claimer", "inspector", "killer", "protector",
)
TARGET_KEYS = (
    "target", "victim", "to", "against", "accused", "suspect", "voted_for",
    "vote_for", "nominee", "chosen", "protected", "inspected", "killed",
    "exiled", "subject", "target_seat",
)

LAST_PROTECTED = {}
INSPECTED_BY_GAME = {}


def as_text(value):
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value)


def first_value(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and not isinstance(
            mapping[key], (dict, list, tuple, set)
        ):
            return mapping[key]
    return None


def int_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    return None


def numbers_in_text(value):
    text = as_text(value)
    numbers = []
    current = []
    for char in text:
        if char.isdigit():
            current.append(char)
        elif current:
            numbers.append(int("".join(current)))
            current = []
    if current:
        numbers.append(int("".join(current)))
    return numbers


def seat_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        lowered = text.lower()
        if "seat" in lowered or lowered.startswith("player") or "#" in text:
            numbers = numbers_in_text(text)
            if numbers:
                return numbers[0]
        return None
    if isinstance(value, dict):
        for key in SEAT_KEYS:
            if key in value:
                seat = seat_value(value[key])
                if seat is not None:
                    return seat
    return None


def seat_first(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping:
            seat = seat_value(mapping[key])
            if seat is not None:
                return seat
    return None


def unique_seats(values):
    result = []
    seen = set()
    for value in values:
        seat = seat_value(value)
        if seat is not None and seat not in seen:
            seen.add(seat)
            result.append(seat)
    return result


def seat_set(value):
    result = set()
    if isinstance(value, (list, tuple, set)):
        for item in value:
            seat = seat_value(item)
            if seat is not None:
                result.add(seat)
    elif isinstance(value, dict):
        direct = seat_first(value, SEAT_KEYS)
        if direct is not None:
            result.add(direct)
        else:
            for key, item in value.items():
                seat = seat_value(key)
                if seat is None:
                    continue
                if isinstance(item, bool):
                    if item:
                        result.add(seat)
                elif item is not None:
                    result.add(seat)
    else:
        seat = seat_value(value)
        if seat is not None:
            result.add(seat)
    return result


def mentioned_seats(value):
    text = as_text(value).lower()
    found = []
    for marker in ("seat", "player", "#"):
        start = 0
        while True:
            position = text.find(marker, start)
            if position < 0:
                break
            index = position + len(marker)
            while index < len(text) and text[index] in " \t:#":
                index += 1
            end = index
            while end < len(text) and text[end].isdigit():
                end += 1
            if end > index:
                found.append(int(text[index:end]))
            start = position + len(marker)
    if found:
        return unique_seats(found)
    return unique_seats(numbers_in_text(text))


def role_kind(value):
    if isinstance(value, dict):
        for key in ROLE_KEYS + ("team", "name", "kind"):
            if key in value:
                role = role_kind(value[key])
                if role:
                    return role
        return ""
    text = as_text(value).strip().lower()
    if not text:
        return ""
    if "werewolf" in text or "wolf" in text or "lycan" in text:
        return WOLF
    if "seer" in text or "oracle" in text or "prophet" in text:
        return SEER
    if (
        "doctor" in text
        or "healer" in text
        or "medic" in text
        or "nurse" in text
    ):
        return DOCTOR
    if (
        "villager" in text
        or "townsfolk" in text
        or "town" in text
        or "village" in text
        or "human" in text
        or "civilian" in text
    ):
        return VILLAGER
    return ""


def truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in (
            "1", "true", "yes", "alive", "living", "active", "revealed",
        )
    return False


def falsy(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in (
            "0", "false", "no", "dead", "eliminated", "killed", "exiled",
        )
    return False


def player_alive(info):
    if not isinstance(info, dict):
        return None
    for key in ("alive", "is_alive", "living", "is_living", "active"):
        if key in info:
            value = info[key]
            if truthy(value):
                return True
            if falsy(value):
                return False
    for key in ("dead", "is_dead", "eliminated", "is_eliminated"):
        if key in info:
            return not truthy(info[key])
    status = as_text(info.get("status")).strip().lower()
    if status:
        if any(word in status for word in ("dead", "eliminated", "killed", "exiled")):
            return False
        if any(word in status for word in ("alive", "living", "active")):
            return True
    return None


def collect_players(view):
    players = {}
    if not isinstance(view, dict):
        return players
    raw = view.get("players")
    if isinstance(raw, dict):
        for key in ("players", "seats", "list", "roster"):
            if isinstance(raw.get(key), (list, dict)):
                raw = raw[key]
                break

    def add(seat, info):
        if seat is None or not isinstance(info, dict):
            return
        record = players.setdefault(
            seat,
            {"seat": seat, "role": "", "claimed_role": "", "alive": None,
             "revealed": False, "name": ""},
        )
        role = role_kind(first_value(info, ROLE_KEYS))
        if role:
            record["role"] = role
        claim = role_kind(
            first_value(info, ("claimed_role", "role_claim", "claim"))
        )
        if claim:
            record["claimed_role"] = claim
        alive = player_alive(info)
        if alive is not None:
            record["alive"] = alive
        if any(truthy(info.get(key)) for key in (
            "revealed", "role_revealed", "is_revealed", "revealed_role",
        )):
            record["revealed"] = True
        name = first_value(info, ("name", "player_name", "username"))
        if name is not None:
            record["name"] = as_text(name)

    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                seat = seat_first(item, SEAT_KEYS)
                add(index + 1 if seat is None else seat, item)
            else:
                seat = seat_value(item)
                if seat is not None:
                    add(seat, {"alive": True})
    elif isinstance(raw, dict):
        looks_like_player = (
            any(key in raw for key in SEAT_KEYS)
            or "role" in raw
            or "alive" in raw
        )
        if looks_like_player:
            seat = seat_first(raw, SEAT_KEYS)
            add(seat, raw)
        else:
            for key, value in raw.items():
                seat = seat_value(key)
                if seat is None:
                    continue
                if isinstance(value, dict):
                    add(seat, value)
                elif isinstance(value, str):
                    add(seat, {"role": value})
                elif isinstance(value, bool):
                    add(seat, {"alive": value})

    if not players:
        for key in ("seats", "roster", "player_list"):
            raw = view.get(key)
            if isinstance(raw, list):
                for index, item in enumerate(raw):
                    if isinstance(item, dict):
                        seat = seat_first(item, SEAT_KEYS)
                        add(index + 1 if seat is None else seat, item)
    return players


def collect_alive(view, players):
    alive = set()
    have_data = False
    raw = view.get("alive")
    if isinstance(raw, (list, tuple, set)):
        have_data = True
        alive.update(seat_set(raw))
    elif isinstance(raw, dict):
        have_data = True
        for key, value in raw.items():
            seat = seat_value(key)
            if seat is not None and truthy(value):
                alive.add(seat)
    elif raw is not None:
        seat = seat_value(raw)
        if seat is not None:
            have_data = True
            alive.add(seat)

    for seat, info in players.items():
        if info.get("alive") is not None:
            have_data = True
            if info["alive"]:
                alive.add(seat)

    dead = set()
    for key in ("dead", "eliminated", "killed", "exiled", "deaths"):
        value = view.get(key)
        if value:
            have_data = True
            dead.update(seat_set(value))
    if dead:
        alive.difference_update(dead)
        if players:
            alive.update(set(players) - dead)
    if not have_data and players:
        alive.update(players)
    return alive


def find_self(view, players):
    seat = seat_first(view, SEAT_KEYS) if isinstance(view, dict) else None
    role = role_kind(first_value(view, ROLE_KEYS)) if isinstance(view, dict) else ""

    for key in ("you", "me", "self", "identity", "current_player"):
        value = view.get(key) if isinstance(view, dict) else None
        if value is None:
            continue
        if seat is None:
            seat = seat_value(value)
        if isinstance(value, dict):
            if seat is None:
                seat = seat_first(value, SEAT_KEYS)
            if not role:
                role = role_kind(first_value(value, ROLE_KEYS))

    for player_seat, info in players.items():
        is_self = any(truthy(info.get(key)) for key in (
            "you", "is_you", "me", "is_me", "self", "is_self", "current",
        ))
        if as_text(info.get("name")).strip().lower() in ("you", "me", "self"):
            is_self = True
        if is_self:
            if seat is None:
                seat = player_seat
            if not role:
                role = info.get("role", "")
        if player_seat == seat and not role:
            role = info.get("role", "")
    return seat, role


def collect_log_entries(raw, depth=0):
    if depth > 4:
        return []
    entries = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("log"), list):
                entries.extend(collect_log_entries(item["log"], depth + 1))
            else:
                entries.append(item)
    elif isinstance(raw, dict):
        found = False
        for key in ("events", "entries", "log", "history"):
            if key in raw:
                entries.extend(collect_log_entries(raw[key], depth + 1))
                found = True
                break
        if not found:
            for value in raw.values():
                if isinstance(value, list):
                    entries.extend(collect_log_entries(value, depth + 1))
    elif raw is not None:
        entries.append(raw)
    return entries


def increment(mapping, key, amount=1):
    if key is None:
        return
    mapping[key] = mapping.get(key, 0) + amount


def empty_signals():
    return {
        "vote_counts": {},
        "accused_counts": {},
        "accused_by": {},
        "outgoing_accusations": {},
        "speech_counts": {},
        "mention_counts": {},
        "last_accused_order": {},
        "vote_edges": [],
        "accusation_pairs": [],
        "claimed_roles": {WOLF: set(), VILLAGER: set(), SEER: set(), DOCTOR: set()},
        "revealed_roles": {},
        "inspections": [],
        "inspected": set(),
        "seer_named": set(),
        "partners": set(),
        "last_protected": None,
        "players": {},
        "alive": set(),
    }


def add_claim(signals, seat, role):
    if seat is None or role not in signals["claimed_roles"]:
        return
    signals["claimed_roles"][role].add(seat)


def text_claims_wolf(text):
    lowered = as_text(text).lower()
    if "not a werewolf" in lowered or "not werewolf" in lowered:
        return False
    if "not guilty" in lowered or "is a villager" in lowered:
        return False
    return (
        "werewolf" in lowered
        or " wolf" in lowered
        or lowered.startswith("wolf")
        or "guilty" in lowered
        or "evil" in lowered
    )


def analyze_log(view):
    signals = empty_signals()
    if not isinstance(view, dict):
        return signals
    raw_log = view.get("log")
    if raw_log is None:
        raw_log = view.get("history")

    for order, item in enumerate(collect_log_entries(raw_log)):
        if isinstance(item, dict):
            entry = dict(item)
        elif isinstance(item, str):
            entry = {"text": item}
        else:
            continue

        kind = as_text(first_value(entry, (
            "decision", "action", "type", "kind", "event_type", "event",
        ))).strip().lower()
        merged = dict(entry)
        for nested_key in (
            "data", "details", "payload", "vote", "speech", "claim", "inspect",
            "result", "action_detail",
        ):
            nested = entry.get(nested_key)
            if isinstance(nested, dict):
                if not kind:
                    kind = nested_key
                for key, value in nested.items():
                    merged.setdefault(key, value)

        text = as_text(first_value(merged, (
            "text", "message", "content", "speech", "statement", "utterance",
            "quote", "reason", "detail", "result_text",
        )))
        if not text:
            for key in ("speech", "claim", "announcement", "result"):
                if isinstance(entry.get(key), str):
                    text = entry[key]
                    break

        lowered = text.strip().lower()
        blob = (kind + " " + lowered).strip()
        actor = seat_first(merged, ACTOR_KEYS)
        target = seat_first(merged, TARGET_KEYS)
        event_role = role_kind(first_value(merged, ROLE_KEYS + (
            "result_role", "revealed_role",
        )))
        mentions = mentioned_seats(text)

        for mentioned in mentions:
            increment(signals["mention_counts"], mentioned)

        vote_event = any(word in kind for word in (
            "vote", "voted", "ballot", "lynch", "exile", "banish", "trial",
        )) and not any(word in kind for word in ("result", "tally", "summary"))
        if not vote_event and not any(word in kind for word in (
            "kill", "inspect", "check", "protect", "heal", "guard",
        )):
            vote_event = any(phrase in lowered for phrase in (
                "i vote", "we vote", "voted for", "vote for",
            ))

        inspect_event = any(word in kind for word in (
            "inspect", "check", "vision", "investigat",
        )) or any(word in lowered for word in (
            "inspected", "checked", "my vision",
        ))
        structural = any(word in kind for word in (
            "kill", "protect", "heal", "guard", "inspect", "check", "vision",
        ))

        reveal_event = any(word in kind for word in (
            "reveal", "death", "died", "killed", "eliminat", "exile", "exil",
            "lynch_result", "voted_out", "role_public",
        ))
        accuse_event = vote_event or any(word in kind for word in (
            "accus", "suspect", "point", "finger",
        ))
        if not structural and not reveal_event:
            accuse_event = accuse_event or any(word in lowered for word in (
                "accus", "suspect", "suspicious", "werewolf", "wolf", "guilty",
                "evil", "point at", "vote for", "voted for",
            ))
        if structural and not vote_event:
            accuse_event = any(word in kind for word in ("accus", "suspect"))

        if target is None and (vote_event or accuse_event or inspect_event):
            for mentioned in mentions:
                if mentioned != actor:
                    target = mentioned
                    break

        speaking = any(word in kind for word in (
            "speak", "say", "talk", "message", "claim", "discuss", "statement",
        ))
        if lowered and not speaking and not structural and not vote_event:
            speaking = True
        if speaking and actor is not None:
            increment(signals["speech_counts"], actor)

        if vote_event and target is not None and target != actor:
            increment(signals["vote_counts"], target)
            if actor is not None:
                signals["vote_edges"].append((actor, target))

        if accuse_event and target is not None and target != actor:
            increment(signals["accused_counts"], target)
            signals["last_accused_order"][target] = order
            if actor is not None:
                by_target = signals["accused_by"].setdefault(target, {})
                increment(by_target, actor)
                increment(signals["outgoing_accusations"], actor)
                signals["accusation_pairs"].append((actor, target))

        if reveal_event and event_role:
            subject = target if target is not None else actor
            if subject is not None:
                signals["revealed_roles"][subject] = event_role

        first_person = any(phrase in lowered for phrase in (
            "i am ", "i'm ", "im ", "me, the ", "as the ", "my role is ",
        ))
        claim_marker = (
            "claim" in blob
            or "reveal" in kind
            or first_person
            or any(phrase in lowered for phrase in ("role is ", "i was "))
        )
        if event_role and actor is not None and claim_marker:
            add_claim(signals, actor, event_role)
        if actor is not None:
            if claim_marker or "seer" in kind:
                if "seer" in lowered or "oracle" in lowered or "prophet" in lowered:
                    add_claim(signals, actor, SEER)
                if any(word in lowered for word in ("doctor", "healer", "medic")):
                    add_claim(signals, actor, DOCTOR)
                if any(word in lowered for word in ("werewolf", " wolf", "lycan")):
                    add_claim(signals, actor, WOLF)
                if any(word in lowered for word in ("villager", "townsfolk", "townie")):
                    add_claim(signals, actor, VILLAGER)

        if inspect_event and target is not None:
            result_role = event_role or role_kind(text)
            signals["inspections"].append((actor, target, result_role, lowered))
            signals["inspected"].add(target)

        if any(word in kind for word in ("protect", "heal", "guard")):
            if target is not None:
                signals["last_protected"] = target

    return signals


def option_seats(value):
    if isinstance(value, dict):
        for key in ("options", "seats", "choices"):
            if key in value:
                return option_seats(value[key])
        return unique_seats(value.keys())
    if isinstance(value, (list, tuple, set)):
        return unique_seats(value)
    seat = seat_value(value)
    return [] if seat is None else [seat]


def analyze(view):
    if not isinstance(view, dict):
        view = {}
    players = collect_players(view)
    self_seat, role = find_self(view, players)
    alive = collect_alive(view, players)
    signals = analyze_log(view)
    signals["players"] = players
    signals["alive"] = alive

    partners = set()
    for key in (
        "partners", "teammates", "wolf_partners", "werewolves", "wolves",
        "allies", "known_werewolves", "pack",
    ):
        if key in view:
            partners.update(seat_set(view[key]))
    if isinstance(view.get("you"), dict) and "partners" in view["you"]:
        partners.update(seat_set(view["you"]["partners"]))
    for player_seat, info in players.items():
        if info.get("role") == WOLF:
            partners.add(player_seat)
    partners.discard(self_seat)
    signals["partners"] = partners

    for player_seat, info in players.items():
        if info.get("claimed_role"):
            add_claim(signals, player_seat, info["claimed_role"])
        if info.get("role") and (info.get("revealed") or info.get("alive") is False):
            signals["revealed_roles"][player_seat] = info["role"]

    for key in ("claimed_seer", "seer_claims", "seer_claim"):
        if key in view:
            for claimed in seat_set(view[key]):
                add_claim(signals, claimed, SEER)
    for key in ("claimed_doctor", "doctor_claims", "doctor_claim"):
        if key in view:
            for claimed in seat_set(view[key]):
                add_claim(signals, claimed, DOCTOR)

    claims = view.get("claims")
    if isinstance(claims, dict):
        for key, value in claims.items():
            claimed = seat_value(key)
            claimed_role = role_kind(value)
            add_claim(signals, claimed, claimed_role)
    elif isinstance(claims, list):
        for item in claims:
            if not isinstance(item, dict):
                continue
            claimed = seat_first(item, SEAT_KEYS + ("player_id", "index"))
            claimed_role = role_kind(first_value(item, ROLE_KEYS + ("claim",)))
            add_claim(signals, claimed, claimed_role)

    for key in ("revealed_roles", "public_roles", "revealed"):
        raw = view.get(key)
        if isinstance(raw, dict):
            for seat, value in raw.items():
                revealed_seat = seat_value(seat)
                revealed_role = role_kind(value)
                if revealed_seat is not None and revealed_role:
                    signals["revealed_roles"][revealed_seat] = revealed_role

    for key in ("inspected", "inspected_seats", "checked", "checked_seats"):
        if key in view:
            signals["inspected"].update(seat_set(view[key]))
    for key in ("known_roles", "inspection_results", "check_results", "seer_results"):
        raw = view.get(key)
        if isinstance(raw, dict):
            for seat, value in raw.items():
                known_seat = seat_value(seat)
                known_role = role_kind(value)
                if known_seat is None:
                    continue
                signals["inspected"].add(known_seat)
                if known_role == WOLF:
                    signals["seer_named"].add(known_seat)

    for item in view.get("inspections", []) if isinstance(
        view.get("inspections"), list
    ) else []:
        if isinstance(item, dict):
            inspected_seat = seat_first(item, TARGET_KEYS + SEAT_KEYS)
            if inspected_seat is not None:
                signals["inspected"].add(inspected_seat)

    for key in ("last_protected", "last_protect", "previous_protection"):
        if key in view:
            previous = seat_value(view[key])
            if previous is not None:
                signals["last_protected"] = previous
    return self_seat, role, signals


def living_seats(signals):
    alive = sorted(signals.get("alive", set()))
    if alive:
        return alive
    return sorted(signals.get("players", {}).keys())


def candidate_seats(options, signals, self_seat=None, excluded=None):
    raw = option_seats(options)
    source = list(raw)
    if not source:
        source = living_seats(signals)
    alive = signals.get("alive", set())
    if alive and source:
        filtered = [seat for seat in source if seat in alive]
        if filtered:
            source = filtered
    if self_seat is not None:
        source = [seat for seat in source if seat != self_seat]
    if excluded:
        source = [seat for seat in source if seat not in excluded]
    return unique_seats(source)


def best_by(candidates, score):
    if not candidates:
        return None
    best = candidates[0]
    best_score = score(best)
    for seat in candidates[1:]:
        current = score(seat)
        if current > best_score:
            best = seat
            best_score = current
    return best


def other_accuser_count(signals, seat, self_seat):
    actors = signals["accused_by"].get(seat, {})
    return sum(1 for actor in actors if actor != self_seat)


def seer_named_seats(signals, role, self_seat):
    named = set(signals["seer_named"])
    seers = {
        seat for seat, revealed in signals["revealed_roles"].items()
        if revealed == SEER
    }
    if role == SEER and self_seat is not None:
        seers.add(self_seat)
    for actor, target, result_role, text in signals["inspections"]:
        trustworthy = actor is None or actor in seers
        if not trustworthy:
            continue
        if result_role == WOLF or text_claims_wolf(text):
            named.add(target)
    for actor, target in signals["accusation_pairs"]:
        if actor in seers:
            named.add(target)
    return named


def revealed_villagers(signals):
    return {
        seat for seat, revealed in signals["revealed_roles"].items()
        if revealed == VILLAGER
    }


def villager_target(candidates, signals, role, self_seat):
    if not candidates:
        return None

    named = seer_named_seats(signals, role, self_seat)
    named_candidates = [seat for seat in candidates if seat in named]
    if named_candidates:
        return best_by(named_candidates, lambda seat: (
            other_accuser_count(signals, seat, self_seat),
            signals["accused_counts"].get(seat, 0),
            signals["vote_counts"].get(seat, 0),
            signals["mention_counts"].get(seat, 0),
            -seat,
        ))

    villagers = revealed_villagers(signals)
    revealed_voter_seats = {
        actor for actor, target in signals["vote_edges"] if target in villagers
    }
    voter_candidates = [seat for seat in candidates if seat in revealed_voter_seats]
    if voter_candidates:
        return best_by(voter_candidates, lambda seat: (
            other_accuser_count(signals, seat, self_seat),
            signals["accused_counts"].get(seat, 0),
            signals["mention_counts"].get(seat, 0),
            -seat,
        ))

    accused_candidates = [
        seat for seat in candidates
        if other_accuser_count(signals, seat, self_seat) > 0
    ]
    if accused_candidates:
        return best_by(accused_candidates, lambda seat: (
            other_accuser_count(signals, seat, self_seat),
            signals["accused_counts"].get(seat, 0),
            signals["last_accused_order"].get(seat, -1),
            signals["mention_counts"].get(seat, 0),
            -seat,
        ))

    spoke = [seat for seat in candidates if seat in signals["speech_counts"]]
    if spoke:
        return min(
            spoke,
            key=lambda seat: (signals["speech_counts"].get(seat, 0), seat),
        )
    return candidates[0]


def choose_vote(options, signals, self_seat, role):
    candidates = candidate_seats(options, signals, self_seat)
    if not candidates:
        return None
    if role == WOLF:
        non_partners = [
            seat for seat in candidates if seat not in signals["partners"]
        ]
        if non_partners:
            candidates = non_partners
        accused_me = signals["accused_by"].get(self_seat, {})
        return best_by(candidates, lambda seat: (
            accused_me.get(seat, 0),
            signals["accused_counts"].get(seat, 0),
            signals["vote_counts"].get(seat, 0),
            signals["mention_counts"].get(seat, 0),
            -seat,
        ))
    return villager_target(candidates, signals, role, self_seat)


def choose_speak_target(signals, self_seat, role):
    candidates = [seat for seat in living_seats(signals) if seat != self_seat]
    if not candidates:
        return None
    if role == WOLF:
        non_partners = [
            seat for seat in candidates if seat not in signals["partners"]
        ]
        if non_partners:
            candidates = non_partners
        return best_by(candidates, lambda seat: (
            signals["vote_counts"].get(seat, 0)
            + signals["mention_counts"].get(seat, 0)
            + signals["accused_counts"].get(seat, 0),
            signals["vote_counts"].get(seat, 0),
            signals["mention_counts"].get(seat, 0),
            -seat,
        ))
    return villager_target(candidates, signals, role, self_seat)


def choose_kill(options, signals, self_seat):
    candidates = candidate_seats(
        options, signals, self_seat, signals["partners"]
    )
    if not candidates:
        candidates = candidate_seats(options, signals, self_seat)
    if not candidates:
        candidates = [seat for seat in living_seats(signals) if seat != self_seat]
    if not candidates:
        candidates = option_seats(options)
    if not candidates:
        return None

    claimed_seers = signals["claimed_roles"][SEER]
    seer_candidates = [seat for seat in candidates if seat in claimed_seers]
    if seer_candidates:
        return min(seer_candidates)

    wolves = set(signals["partners"])
    if self_seat is not None:
        wolves.add(self_seat)

    def accused_wolf_score(seat):
        return sum(
            signals["accused_by"].get(wolf, {}).get(seat, 0) for wolf in wolves
        )

    accusers = [seat for seat in candidates if accused_wolf_score(seat) > 0]
    if accusers:
        return best_by(accusers, lambda seat: (accused_wolf_score(seat), -seat))
    return min(candidates)


def choose_protect(options, signals, self_seat, previous):
    candidates = candidate_seats(options, signals, self_seat)
    if previous is not None:
        candidates = [seat for seat in candidates if seat != previous]
    if not candidates:
        return None
    claimed_seers = signals["claimed_roles"][SEER]
    seer_candidates = [seat for seat in candidates if seat in claimed_seers]
    if seer_candidates:
        return best_by(seer_candidates, lambda seat: (
            signals["vote_counts"].get(seat, 0),
            signals["accused_counts"].get(seat, 0),
            -seat,
        ))
    return best_by(candidates, lambda seat: (
        signals["vote_counts"].get(seat, 0),
        signals["accused_counts"].get(seat, 0),
        signals["mention_counts"].get(seat, 0),
        -seat,
    ))


def choose_inspect(options, signals, self_seat, already_inspected):
    candidates = candidate_seats(options, signals, self_seat)
    if not candidates:
        return None
    fresh = [seat for seat in candidates if seat not in already_inspected]
    if fresh:
        candidates = fresh
    claimed = set()
    for seats in signals["claimed_roles"].values():
        claimed.update(seats)
    return best_by(candidates, lambda seat: (
        1 if seat in claimed else 0,
        signals["outgoing_accusations"].get(seat, 0),
        signals["mention_counts"].get(seat, 0),
        -seat,
    ))


def fit_text(parts, max_chars):
    if max_chars is None or max_chars < 1:
        return None
    for text in parts:
        one_line = " ".join(text.split())
        if one_line and one_line.isascii() and len(one_line) <= max_chars:
            return one_line
    return None


def make_speak_text(target, max_chars):
    base = ("I'm a villager.", "Villager here.", "Villager.")
    if target is not None:
        with_target = (
            "I'm a villager. Seat {} seems suspicious.".format(target),
            "Villager here. Seat {} is suspicious.".format(target),
            "Villager: I suspect seat {}.".format(target),
            "Villager: suspect seat {}.".format(target),
            "Villager, seek out seat {}.".format(target),
            "Villager: {} is suspicious.".format(target),
            "Villager: suspect {}.".format(target),
            "Villager; {} suspicious.".format(target),
            "Villager: {} sus.".format(target),
            "Villager: {} sus".format(target),
        )
        text = fit_text(with_target, max_chars)
        if text:
            return text
    return fit_text(base, max_chars)


def game_key(game):
    try:
        return ("int", int(game))
    except (TypeError, ValueError):
        return ("str", as_text(game))


def build_action(item):
    game = item.get("game")
    decision = as_text(item.get("decision")).strip().lower()
    view = item.get("view")
    if not isinstance(view, dict):
        view = {}
    self_seat, role, signals = analyze(view)

    if decision == "speak":
        max_chars = int_value(item.get("max_chars"))
        target = choose_speak_target(signals, self_seat, role)
        text = make_speak_text(target, max_chars)
        if text is None:
            return {"game": game, "decision": "speak", "pass": True}
        return {"game": game, "decision": "speak", "text": text}

    options = item.get("options")
    if decision == "vote":
        target = choose_vote(options, signals, self_seat, role)
    elif decision == "kill":
        target = choose_kill(options, signals, self_seat)
    elif decision == "protect":
        key = game_key(game)
        previous = signals.get("last_protected")
        if previous is None:
            previous = LAST_PROTECTED.get(key)
        target = choose_protect(options, signals, self_seat, previous)
        if target is not None:
            LAST_PROTECTED[key] = target
    elif decision == "inspect":
        key = game_key(game)
        inspected = set(signals.get("inspected", set()))
        inspected.update(INSPECTED_BY_GAME.get(key, set()))
        target = choose_inspect(options, signals, self_seat, inspected)
        if target is not None:
            INSPECTED_BY_GAME.setdefault(key, set()).add(target)
    else:
        return None
    return {"game": game, "decision": decision, "target": target}


def fallback_action(item):
    game = item.get("game")
    decision = as_text(item.get("decision")).strip().lower()
    if decision == "speak":
        return {"game": game, "decision": "speak", "pass": True}
    options = option_seats(item.get("options"))
    target = options[0] if options else None
    return {"game": game, "decision": decision, "target": target}


def post_json(base_url, path, payload):
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    if not body:
        return {}
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def main():
    base_url = os.environ["MAKEFUN_ENV_URL"].rstrip("/")
    while True:
        try:
            observation = post_json(base_url, "/observe", {})
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 409):
                exc.close()
                continue
            raise

        if observation.get("done") is True:
            return

        pending = observation.get("pending")
        if isinstance(pending, dict):
            pending = [pending]
        if not isinstance(pending, list):
            continue

        for item in pending:
            if not isinstance(item, dict):
                continue
            try:
                action = build_action(item)
            except Exception:
                action = fallback_action(item)
            if action is None:
                continue
            try:
                post_json(base_url, "/act", action)
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 409):
                    exc.close()
                    break
                raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("fatal:", exc, flush=True)
        raise SystemExit(1)
