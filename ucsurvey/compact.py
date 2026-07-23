"""Compact result codes: a whole survey session in one email-safe line.

A respondent's screens are fully determined by (email, sessionId, arm,
extraBlocks) plus the survey build — so their answers compress to just the
picks: 2 bytes per screen. The survey's "Email my results" button packs
header + picks into a short `UCS1.<header>.<payload>` code that fits in a
mailto: body (no attachments, no downloads), and ingest.py expands codes
back into full result files by re-deriving the screens.

Wire format (must stay in lockstep with the survey template's
COMPACT-PARITY block; tests/test_compact.py enforces it):

    UCS1 . base64url(header JSON) . base64url(payload bytes)

    header: {v,s,e,n,r,o,f,a,x,h,g,t,d} = version, sessionId, email, name,
            role, org, familiarity, arm, extraBlocks, catalogHash,
            designHash, startedAt, exportedAt
    payload, per answered screen: byte0 = 255 if skipped else best*4+worst
             (positions in the shown order), byte1 = responseMs/100 (cap 254)

Codes are decodable only against the exact build they came from (the
designHash guards this) — the downloaded .json remains the archival format.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

from .design import derive_respondent_sets

CODE_RE = re.compile(r"UCS1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]*)")


class CodeError(ValueError):
    pass


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def design_hash(payload: dict) -> str:
    """Fingerprint of the generated designs; changes if catalog, seeds, or
    design-affecting config change — exactly when codes stop being decodable."""
    basis = {
        "arms": {k: payload["arms"][k]["master"] for k in sorted(payload["arms"])},
        "cont": payload["continuationMaster"],
    }
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]


def find_codes(text: str) -> list[str]:
    return ["UCS1.{}.{}".format(*m) for m in CODE_RE.findall(text)]


def encode(result: dict, payload: dict) -> str:
    """Full result dict -> compact code (mirror of the survey JS; used by tests)."""
    r = result["respondent"]
    header = {
        "v": 1, "s": result["sessionId"], "e": r["email"], "n": r["name"],
        "r": r["role"], "o": r["organization"], "f": r["familiarity"],
        "a": result["arm"], "x": result.get("extraBlocks", 0),
        "h": result["catalogVersionHash"], "g": design_hash(payload),
        "t": result.get("startedAt", ""), "d": result.get("exportedAt", ""),
    }
    body = bytearray()
    for s in result["sets"]:
        if s["skipped"]:
            body.append(255)
        else:
            body.append(s["shown"].index(s["best"]) * 4 + s["shown"].index(s["worst"]))
        body.append(min(254, round((s.get("responseMs") or 0) / 100)))
    hjson = json.dumps(header, separators=(",", ":"), ensure_ascii=False)
    return f"UCS1.{_b64url_encode(hjson.encode())}.{_b64url_encode(bytes(body))}"


def decode(code: str, payload: dict) -> dict:
    """Compact code -> full result dict, by re-deriving the screens shown."""
    m = CODE_RE.fullmatch(code.strip())
    if not m:
        raise CodeError("not a UCS1 results code")
    try:
        header = json.loads(_b64url_decode(m.group(1)))
        body = _b64url_decode(m.group(2))
    except Exception as exc:
        raise CodeError(f"corrupted code: {exc}") from exc
    if header.get("v") != 1:
        raise CodeError(f"unsupported code version {header.get('v')}")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(header.get("s", ""))):
        raise CodeError("sessionId contains characters the survey never produces")
    if header["h"] != payload["catalogVersionHash"]:
        raise CodeError(
            f"code was produced by catalog {header['h']}, current is "
            f"{payload['catalogVersionHash']} — codes can only be decoded "
            "against the exact survey build they came from; ask for the "
            "respondent's downloaded .json instead"
        )
    if header["g"] != design_hash(payload):
        raise CodeError(
            "code was produced by a different survey build (design seed or "
            "config changed since) — rebuild with the original settings or "
            "use the respondent's downloaded .json"
        )
    if len(body) % 2:
        raise CodeError("corrupted code: odd payload length")

    item_ids = [it["id"] for it in payload["catalog"]]
    email = str(header["e"]).lower()
    seed = f"{email}|{header['s']}"
    plan = derive_respondent_sets(payload["arms"][header["a"]]["master"], item_ids, seed)
    for b in range(1, int(header["x"]) + 1):
        plan += derive_respondent_sets(payload["continuationMaster"], item_ids,
                                       f"{seed}|cont{b}")
    n_sets = len(body) // 2
    if n_sets > len(plan):
        raise CodeError(f"code claims {n_sets} screens but the design has {len(plan)}")

    sets = []
    for i in range(n_sets):
        pick, ms = body[2 * i], body[2 * i + 1]
        shown = plan[i]
        skipped = pick == 255
        if not skipped and (pick > 15 or pick // 4 == pick % 4):
            raise CodeError(f"corrupted code: invalid pick byte {pick} at screen {i}")
        sets.append({
            "index": i, "shown": shown,
            "best": None if skipped else shown[pick // 4],
            "worst": None if skipped else shown[pick % 4],
            "skipped": skipped, "answeredAt": "", "responseMs": ms * 100,
        })

    return {
        "schemaVersion": 1, "tool": "ucsurvey", "sessionId": header["s"],
        "respondent": {"name": header["n"], "email": email, "role": header["r"],
                       "organization": header["o"], "familiarity": header["f"]},
        "catalogVersionHash": header["h"], "arm": header["a"],
        "designSeed": seed, "startedAt": header.get("t", ""),
        "exportedAt": header.get("d", ""), "plannedScreens": len(plan),
        "extraBlocks": int(header["x"]), "sets": sets, "fromCompactCode": True,
    }
