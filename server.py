"""Local server for 序名; four pillars and candidate suggestions are distinct."""
from __future__ import annotations
import json, os, re, sqlite3
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import bazi
import phonetics
import tradition
import naming_rules
import name_review
import literary_engine
import naming_corpus
import naming_auxiliary
import mingli
import solar_time
import classical_sources

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "naming.sqlite3"
DIST = ROOT / "frontend" / "dist"
# Only assets required by the application are public. In particular, never
# expose the SQLite database, source files, repository metadata or directories.
PUBLIC_ASSETS = frozenset({
    "/", "/index.html", "/styles.css", "/engine.js", "/app.js",
    "/service-worker.js", "/keepsake.js", "/manifest.webmanifest", "/favicon.svg",
    "/data/character-catalog.json", "/data/classics.json", "/data/product.json",
})
ZONE_LABELS = {
    "Asia/Shanghai": "中国标准时间 UTC+8",
    "Asia/Taipei": "台北时间 UTC+8",
    "Asia/Hong_Kong": "香港时间 UTC+8",
}

def valid_source(source) -> bool:
    """A verified label requires traceable metadata, plus actual human review."""
    if not isinstance(source, dict) or not isinstance(source.get("description"), str) or not source["description"].strip():
        return False
    status = source.get("verification_status")
    if status in ("demo", "pending"):
        return True
    if status != "verified":
        return False
    reference = source.get("reference")
    if not isinstance(reference, dict):
        return False
    fields = ("title", "edition", "citation", "license", "reviewed_by", "reviewed_at", "url")
    if any(not isinstance(reference.get(key), str) or not reference[key].strip() for key in fields):
        return False
    url = urlparse(reference["url"])
    if url.scheme not in ("https", "http") or not url.netloc:
        return False
    try:
        date.fromisoformat(reference["reviewed_at"])
    except ValueError:
        return False
    return True

def load_names() -> list[dict]:
    """Load the single candidate catalog, rejecting incomplete or duplicated data."""
    data = json.loads((DATA / "names.json").read_text(encoding="utf-8"))
    names = data.get("names")
    if not isinstance(names, list) or not names:
        raise ValueError("candidate catalog is empty or invalid")
    seen = set()
    for item in names:
        given = item.get("given")
        source = item.get("meaning_source", {})
        if (not isinstance(given, str) or not 1 <= len(given) <= 3 or given in seen
            or not isinstance(item.get("pinyin"), str) or not item["pinyin"]
            or not isinstance(item.get("meaning"), str) or not item["meaning"]
            or not isinstance(item.get("tags"), list) or not item["tags"]
            or any(not isinstance(tag, str) for tag in item["tags"])
            or not isinstance(item.get("styles"), list) or any(not isinstance(style, str) for style in item["styles"])
            or not isinstance(item.get("genders"), list) or any(g not in ("unknown", "male", "female") for g in item["genders"])
            or not valid_source(source)
            ):
            raise ValueError(f"candidate catalog contains invalid record: {given!r}")
        seen.add(given)
    return names


def init_db() -> None:
    # Keep the existing SQLite catalog for compatibility; the checked-in JSON
    # is the authoritative source for both selection and presentation.
    classical_sources.registry()
    naming_corpus.snapshot()
    DATA.mkdir(exist_ok=True)
    facts = naming_rules.catalog()
    # Legacy base_score remains zero; current ranking has no preset score.
    rows = []
    for item in load_names():
        elements = dict.fromkeys(facts.get(char, {}).get("element") for char in item["given"])
        rows.append((item["given"], item["meaning"], ",".join(e for e in elements if e), ",".join(item["styles"]), 0))
    with sqlite3.connect(DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS candidates (given TEXT PRIMARY KEY, meaning TEXT, element TEXT, styles TEXT, base_score INTEGER)")
        conn.executemany("INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", ("schema_version", "2.0.0"))
        conn.commit()

def character_preferences(payload: dict) -> tuple[set[str], set[str]]:
    """Explicit fields are individual Chinese characters separated by punctuation.

    The previous free-text field remains supported for older API clients.
    """
    def parse_field(key: str) -> set[str]:
        value = payload.get(key, "") or ""
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError(f"{key} must contain Chinese characters and separators only")
        chars = set()
        for char in value:
            if phonetics.is_han(char):
                chars.add(char)
            elif not (char.isspace() or char in "，,、；;‘’“”'\"：:"):
                raise ValueError(f"{key} must contain Chinese characters and separators only")
        return chars

    legacy = str(payload.get("chars", "") or "")
    def legacy_field(words: str) -> set[str]:
        found = set()
        for match in re.finditer(rf"(?:{words})[：:\s‘“\"']*([^，,；;\s]+)", legacy):
            found.update(char for char in match.group(1) if phonetics.is_han(char))
        return found

    liked = parse_field("likedChars") if "likedChars" in payload else legacy_field("喜欢|喜歡")
    avoided = parse_field("avoidedChars") if "avoidedChars" in payload else legacy_field("避开|避開|不要|不取")
    if liked & avoided:
        raise ValueError("likedChars and avoidedChars cannot overlap")
    return liked, avoided

def analyze(payload: dict, *, recommend: bool = True) -> dict:
    algorithm = payload.get("algorithm", "legacy_v2")
    if algorithm not in ("legacy_v2", "literary_v3"):
        raise ValueError("algorithm must be legacy_v2 or literary_v3")
    surname = str(payload.get("surname", "")).strip()
    if not 1 <= len(surname) <= 2 or not all(phonetics.is_han(char) for char in surname):
        raise ValueError("surname must contain one or two Chinese characters")
    mode = str(payload.get("mode", "due_date"))
    if mode not in ("due_date", "born"):
        raise ValueError("mode must be due_date or born")
    purpose = str(payload.get("purpose", "newborn"))
    if purpose not in ("newborn", "rename"):
        raise ValueError("purpose must be newborn or rename")
    if purpose == "rename" and mode != "born":
        raise ValueError("rename purpose requires born mode")
    gender = str(payload.get("gender", "unknown"))
    if gender not in ("male", "female", "unknown"):
        raise ValueError("gender must be male, female, or unknown")
    place = str(payload.get("place") or "").strip()
    city = solar_time.selected_city(payload)
    zone = str(payload.get("zone", city["zone"] if city else "Asia/Shanghai"))
    if zone not in ZONE_LABELS:
        raise ValueError("zone must be Asia/Shanghai, Asia/Taipei, or Asia/Hong_Kong")
    zone_label = ZONE_LABELS[zone]

    # The selected flow alone chooses its clock. Never silently switch a due-date
    # request to actual birth, or mix estimates into a rename report. Legacy
    # date/time aliases remain accepted within the selected flow.
    due_date = str(payload.get("dueDate") or (payload.get("date") if mode == "due_date" else "") or "").strip()
    due_time = str(payload.get("dueTime") or (payload.get("time") if mode == "due_date" else "") or "12:00").strip()
    birth_date = str(payload.get("birthDate") or (payload.get("date") if mode == "born" else "") or "").strip()
    birth_time = str(payload.get("birthTime") or (payload.get("time") if mode == "born" else "") or "").strip()

    if mode == "due_date" and (birth_date or birth_time):
        raise ValueError("due date flow cannot include actual birth information; choose born mode")
    if mode == "born" and due_date:
        raise ValueError("born flow cannot include due date information")
    if mode == "due_date" and not due_date:
        raise ValueError("dueDate is required when using due date mode")
    if mode == "born" and (not birth_date or not birth_time):
        raise ValueError("birthDate and exact birthTime are required when already born")
    if birth_date and not birth_time:
        raise ValueError("birthDate and birthTime must be supplied together")
    if birth_time and not birth_date:
        raise ValueError("birthDate and birthTime must be supplied together")
    if due_date:
        date.fromisoformat(due_date)  # Future due dates are valid.
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", due_time):
            raise ValueError("dueTime must use HH:MM format")
    if birth_date:
        parsed_birth = date.fromisoformat(birth_date)
        now_in_zone = datetime.now(ZoneInfo(zone))
        if parsed_birth > now_in_zone.date():
            raise ValueError("actual birth date cannot be in the future")
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", birth_time):
            raise ValueError("birthTime must use HH:MM format")
        parsed_birth_time = time.fromisoformat(birth_time)
        if parsed_birth == now_in_zone.date() and parsed_birth_time > now_in_zone.time().replace(second=0, microsecond=0):
            raise ValueError("birthTime cannot be in the future")

    actual_complete = mode == "born"
    basis_date = birth_date if actual_complete else due_date
    basis_time = birth_time if actual_complete else due_time
    try:
        length = int(payload.get("length", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("length must be 1, 2, or 3") from exc
    if length not in (1, 2, 3):
        raise ValueError("length must be 1, 2, or 3")
    try:
        candidate_count = int(payload.get("candidateCount", payload.get("count", 3)))
    except (TypeError, ValueError) as exc:
        raise ValueError("candidateCount must be an integer from 1 to 11") from exc
    if candidate_count < 1 or candidate_count > 11:
        raise ValueError("candidateCount must be an integer from 1 to 11")
    parents = str(payload.get("parents", "")).strip()
    current_name = str(payload.get("currentName", "")).strip()
    if purpose == "rename":
        name_review.validate(surname, current_name)
    else:
        current_name = ""
    meaning = str(payload.get("meaning", "")).strip()
    liked, avoided = character_preferences(payload)
    styles = payload.get("styles", []) or []
    if not isinstance(styles, list) or any(not isinstance(style, str) for style in styles):
        raise ValueError("styles must be a list of strings")
    clock_options = solar_time.options(payload)
    chart = bazi.calculate(basis_date, basis_time, zone, reference=not actual_complete, **clock_options)
    comparison = None
    scenario = "预产期起名" if mode == "due_date" else "已出生起名" if purpose == "newborn" else "改名 · 实际出生"
    purpose_label = "改名方案" if purpose == "rename" else "新生儿起名"
    workflow = {"id": "rename" if purpose == "rename" else f"newborn_{mode}",
                "label": "改名方案" if purpose == "rename" else f"新生儿起名 · {scenario}",
                "reference": mode == "due_date"}
    names = load_names()
    pool = [item for item in names if len(item["given"]) == length and not any(char in avoided for char in item["given"]) and surname + item["given"] != current_name] if recommend and algorithm == "legacy_v2" else []
    effective_count = min(candidate_count, len(pool))
    try:
        variant = int(payload.get("variant", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("variant must be an integer from 0 to 100000") from exc
    if not 0 <= variant <= 100000:
        raise ValueError("variant must be an integer from 0 to 100000")
    gua = tradition.cast(basis_date, basis_time, zone, reference=chart["reference"], solar_clock=chart["time_correction"]["clock_time"] if chart["time_correction"]["applied"] else None)
    traditional = tradition.chart_details(chart)
    assessment = mingli.analyze(chart, traditional)
    element_preference = payload.get("elementPreference", "auto")
    if not isinstance(element_preference, str):
        raise ValueError("elementPreference must be auto, yongshen, none, 木, 火, 土, 金, or 水")
    naming_reference = naming_rules.target_for(element_preference, gua, assessment)
    family_chars = set()
    if payload.get("honorParents") in (True, "1", "on", "true"):
        family_chars = {char for char in parents if phonetics.is_han(char)} - avoided
    existing_review = name_review.build(surname, current_name, chart, naming_rules.target_for("yongshen", gua, assessment), names) if purpose == "rename" else None
    result = []
    for item in pool:
        given = item["given"]
        pronunciation = phonetics.check(surname, given, item["pinyin"])
        matched = naming_rules.rank(
            item,
            surname,
            pronunciation,
            chart,
            gua,
            naming_reference,
            liked,
            family_chars,
            meaning,
            styles,
            gender,
        )
        source = item["meaning_source"]
        reference = source.get("reference") if source["verification_status"] == "verified" else None
        source_text = (
            source["description"]
            if not reference
            else f"{source['description']}（{reference['title']}，{reference['edition']}，{reference['citation']}；复核：{reference['reviewed_by']}，{reference['reviewed_at']}）"
        )
        result.append(
            {
                **({"rename_comparison": name_review.compare(existing_review, item)} if existing_review else {}),
                "name": surname + given,
                "given": given,
                "pinyin": item["pinyin"],
                "pronunciation": pronunciation,
                "meaning": item["meaning"],
                "tags": matched["elements"] + item["tags"],
                "element": matched["elements"][0] if matched["elements"] else None,
                **matched,
                "source_status": source["verification_status"],
                "source": source_text,
                "source_reference": reference,
            }
        )
    result.sort(key=lambda item: (-item["score"], item["given"]))
    if variant and result:
        offset = (variant * effective_count) % len(result)
        result = result[offset:] + result[:offset]
    algorithm_details = {"algorithm":algorithm}
    if algorithm == "literary_v3":
        algorithm_details["auxiliary_tradition"] = naming_auxiliary.calculate(chart)
        if existing_review:
            # Original-name analysis never depends on the future-name filters.
            review_input = {key:payload[key] for key in ("surname", "surnameReading") if key in payload}
            existing_review = literary_engine.enrich_review(existing_review, surname, chart, review_input)
        if recommend:
            result, algorithm_details = literary_engine.analyze_candidates(payload,surname,chart,gua,naming_reference,liked,avoided,family_chars,meaning,styles,gender,length,candidate_count,variant,current_name,names)
            if existing_review:
                for item in result:
                    item["rename_comparison"] = name_review.compare(existing_review,item)
            effective_count = len(result)
        else:
            algorithm_details = {"algorithm":algorithm,"ranking_version":literary_engine.VERSION,"corpus":naming_corpus.public_stats()}
    if algorithm == "literary_v3":
        algorithm_details["auxiliary_tradition"] = naming_auxiliary.calculate(chart)
    gender_label = {"male": "男", "female": "女", "unknown": "未知"}[gender]
    method = (
        f"{'预产期参考，出生后请重新确认实际时间' if chart['reference'] else '采用实际出生信息'}；"
        f"时区：{zone_label}；四柱按立春、十二节与所选钟面23:00换日计算。"
        f"阴阳、藏干及十神按公开干支规则计算；年月日时起卦得到{gua['hexagram']}，动{gua['moving_line']}爻、变{gua['changed_hexagram']}。"
        f"候选按{naming_reference['label']}、字形部首、读音和文字偏好计算匹配值。"
        f"采用{'真太阳钟' if chart['time_correction']['applied'] else '民用时钟'}确定日/时柱；月令格局与扶抑喜用按{assessment['version']}试算。年、月、日、时均纳入计算；经典引用与序名分析参数可在依据中查看。"
    )
    return {
        "analysis": {
            "primary": None,
            "support": None,
            "bazi": chart,
            "bazi_comparison": comparison,
            "traditional": traditional,
            "mingli": assessment,
            "source_audit": classical_sources.public_index(),
            "gua": gua,
            "naming_reference": naming_reference,
            "ranking_version": naming_rules.VERSION,
            "has_more_candidates": len(pool) > effective_count,
            "family": bool(parents),
            "purpose": purpose_label,
            "purpose_code": purpose,
            "mode": mode,
            "workflow": workflow,
            "phase": "recommendations" if recommend else "name_review",
            "name_review": existing_review,
            "current_name": current_name,
            "scenario": scenario,
            "gender": gender_label,
            "zone": zone,
            "zone_label": zone_label,
            "place": place,
            "time": basis_time,
            "due_date": due_date,
            "due_time": due_time if due_date else "",
            "birth_date": birth_date,
            "birth_time": birth_time,
            "candidate_count": effective_count,
            "requested_candidate_count": candidate_count,
            "available_candidate_count": len(pool),
            "method": method,
            **algorithm_details,
        },
        "candidates": result[:effective_count],
    }


def review_name(payload: dict) -> dict:
    if payload.get("purpose") != "rename":
        raise ValueError("name review requires rename purpose")
    # Future-name filters cannot prevent understanding the existing name.
    # Keep inactive clock fields so mixed-flow requests are still rejected.
    fields = {"surname", "purpose", "mode", "currentName", "gender", "zone", "place",
              "birthDate", "birthTime", "dueDate", "dueTime", "date", "time",
              "timeBasis", "longitude", "locationId", "algorithm", "surnameReading"}
    identity = {key: value for key, value in payload.items() if key in fields}
    identity["elementPreference"] = "yongshen"
    return analyze(identity, recommend=False)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        # Both GET and HEAD use this method; do not allow directory listings or
        # decoded path aliases to bypass the same explicit allowlist.
        route = urlparse(self.path).path
        if route in ("/", "/index.html", "/service-worker.js", "/manifest.webmanifest", "/favicon.svg"):
            if not (DIST / "index.html").is_file():
                self.send_error(503, "Frontend not built; run npm ci and npm run build in frontend")
                return None
            self.directory = str(DIST)
        elif re.fullmatch(r"/assets/[A-Za-z0-9_-]+\.(?:js|css|svg|png|jpe?g|webp|woff2?)", route):
            assets = (DIST / "assets").resolve()
            target = (DIST / route.lstrip("/")).resolve()
            if assets.parent != DIST.resolve() or target.parent != assets or not target.is_file():
                self.send_error(404)
                return None
            self.directory = str(DIST)
        elif route not in PUBLIC_ASSETS:
            self.send_error(404)
            return None
        else:
            self.directory = str(ROOT)
        return super().send_head()

    def end_headers(self):
        # The service worker handles its own versioned asset cache. API results
        # may contain birth data and should not be stored by HTTP caches.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self):
        route = urlparse(self.path).path
        if route == '/api/customer/session':
            # Anonymous capability stub only. A separately deployed customer
            # service takes over this prefix at the reverse proxy.
            return self.json({'customer': None, 'sms_available': False,
                              'purchases_available': False, 'retention_days': 30, 'record_limit': 20})
        if route == "/api/health": return self.json({"status": "ok", "database": DB.name})
        if route == "/api/naming-corpus":
            return self.json(naming_corpus.public_stats())
        if route == "/api/surname-readings":
            surname = parse_qs(urlparse(self.path).query).get("surname",[""])[0]
            if not 1 <= len(surname) <= 2 or not all(phonetics.is_han(c) for c in surname):
                return self.json({"error":"surname must contain one or two Chinese characters"},400)
            return self.json({"surname":surname,"default":literary_engine.name_phonology.surname_reading(surname),"characters":[{"char":c,"readings":phonetics._readings(c)} for c in surname]})
        if route == "/api/name-counts":
            names = load_names()
            algorithm = parse_qs(urlparse(self.path).query).get("algorithm",["legacy_v2"])[0]
            if algorithm not in ("legacy_v2", "literary_v3"):
                return self.json({"error":"algorithm must be legacy_v2 or literary_v3"},400)
            if algorithm == "literary_v3":
                counts = {str(length):len(literary_engine.generate_pool(length,{"element":None,"mode":"none"},set(),set(),set(),set(),"",[],names)[0]) for length in (1,2,3)}
                return self.json({"counts":counts,"algorithm":algorithm,"corpus":naming_corpus.public_stats()})
            return self.json({"counts": {str(length): sum(len(item["given"]) == length for item in names) for length in (1, 2, 3)}})
        if route == "/api/catalog":
            return self.json(json.loads((DATA / "character-catalog.json").read_text(encoding="utf-8")))
        if route == "/api/classics":
            return self.json({**json.loads((DATA / "classics.json").read_text(encoding="utf-8")), "source_audit": classical_sources.public_index()})
        if route == "/api/product":
            return self.json(json.loads((DATA / "product.json").read_text(encoding="utf-8")))
        return super().do_GET()
    def do_POST(self):
        route = urlparse(self.path).path
        if route not in ("/api/analyze", "/api/name-review"):
            return self.send_error(404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0: raise ValueError("invalid Content-Length")
            if size > 64 * 1024: raise ValueError("request too large")
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict): raise ValueError("request body must be a JSON object")
            return self.json(review_name(payload) if route == "/api/name-review" else analyze(payload))
        except (ValueError, json.JSONDecodeError) as exc:
            return self.json({"error": str(exc)}, 400)
    def json(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, fmt, *args):
        if os.environ.get("NAME_SERVER_LOG", ""):
            super().log_message(fmt, *args)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "4173"))
    host = os.environ.get("HOST", "0.0.0.0")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
