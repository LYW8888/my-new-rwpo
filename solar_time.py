"""Apparent solar clock from a validated civil instant and east-positive longitude.

NOAA/Meeus equation of time approximation. The returned clock is a naive wall
clock, never a new timezone or a replacement for the physical solar-term instant.
"""

from datetime import timedelta, timezone
from math import cos, sin, tan, radians, degrees, isfinite
import json
from pathlib import Path
from unicodedata import normalize

VERSION = "apparent-solar-v1"


def locations():
    return json.loads(
        (Path(__file__).resolve().parent / "data" / "locations.json").read_text(encoding="utf-8")
    )


def find_city(place):
    def key(value):
        return "".join(normalize("NFKC", str(value or "")).split()).replace("臺", "台").removesuffix("市")

    name = key(place)
    return next((city for city in locations()["cities"] if key(city["name"]) == name), None) if name else None


def selected_city(payload):
    selected = payload.get("locationId", "") or ""
    if not isinstance(selected, str):
        raise ValueError("locationId must identify a listed city")
    matched = find_city(payload.get("place"))
    if not selected:
        return matched
    city = next((city for city in locations()["cities"] if city["id"] == selected), None)
    if city is None:
        raise ValueError("locationId must identify a listed city")
    if matched and matched["id"] != city["id"]:
        raise ValueError("locationId conflicts with place; select the birth city again")
    return city


def options(payload):
    basis = payload.get("timeBasis", "civil")
    if basis not in ("civil", "apparent_solar"):
        raise ValueError("timeBasis must be civil or apparent_solar")
    city = selected_city(payload)
    value = payload.get("longitude")
    manual = value is not None and value != ""
    if not manual and city:
        value = city["longitude"]
    if value is None or value == "":
        if basis == "apparent_solar":
            raise ValueError("longitude is required for apparent solar time")
        longitude = None
    else:
        if isinstance(value, bool):
            raise ValueError("longitude must be a finite number between -180 and 180")
        try:
            longitude = float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("longitude must be a finite number between -180 and 180") from exc
        if not isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be a finite number between -180 and 180")
    return {
        "time_basis": basis,
        "longitude": longitude,
        "location": {
            "id": city["id"] if city else None,
            "label": city["name"] if city else None,
            "coordinate_source": (
                "city_centre"
                if city and longitude == city["longitude"]
                else "manual" if manual else None
            ),
        },
    }


def equation_of_time(instant):
    """Minutes: apparent solar time minus local mean solar time; east-positive."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("equation of time requires an aware instant")
    jd = instant.astimezone(timezone.utc).timestamp() / 86400 + 2440587.5
    century = (jd - 2451545.0) / 36525
    mean_longitude = radians((280.46646 + century * (36000.76983 + 0.0003032 * century)) % 360)
    mean_anomaly = radians(357.52911 + century * (35999.05029 - 0.0001537 * century))
    eccentricity = 0.016708634 - century * (0.000042037 + 0.0000001267 * century)
    seconds = 21.448 - century * (46.815 + century * (0.00059 - century * 0.001813))
    mean_obliquity = 23 + (26 + seconds / 60) / 60
    obliquity = radians(mean_obliquity + 0.00256 * cos(radians(125.04 - 1934.136 * century)))
    y = tan(obliquity / 2) ** 2
    value = (
        y * sin(2 * mean_longitude)
        - 2 * eccentricity * sin(mean_anomaly)
        + 4 * eccentricity * y * sin(mean_anomaly) * cos(2 * mean_longitude)
        - 0.5 * y * y * sin(4 * mean_longitude)
        - 1.25 * eccentricity * eccentricity * sin(2 * mean_anomaly)
    )
    return 4 * degrees(value)


def hour_boundary_distance(clock):
    seconds = clock.hour * 3600 + clock.minute * 60 + clock.second + clock.microsecond / 1e6
    return min(
        min(abs(seconds - hour * 3600), 86400 - abs(seconds - hour * 3600))
        for hour in range(1, 24, 2)
    )


def correct(local, time_basis="civil", longitude=None, location=None):
    if time_basis not in ("civil", "apparent_solar"):
        raise ValueError("timeBasis must be civil or apparent_solar")
    if local.tzinfo is None or local.utcoffset() is None:
        raise ValueError("solar correction requires an aware civil instant")
    civil_clock = local.replace(tzinfo=None)
    if time_basis == "civil":
        return civil_clock, {
            "version": VERSION,
            "basis": "civil",
            "applied": False,
            "civil_time": local.strftime("%Y-%m-%d %H:%M:%S %z"),
            "clock_time": civil_clock.isoformat(sep=" "),
            "total_minutes": 0,
            "near_hour_boundary": hour_boundary_distance(civil_clock) <= 120,
            "boundary_distance_seconds": round(hour_boundary_distance(civil_clock), 3),
            "notice": "使用所选地区的历史民用时钟；没有经度或均时差修正。",
        }
    if (
        isinstance(longitude, bool)
        or not isinstance(longitude, (int, float))
        or not isfinite(longitude)
        or not -180 <= longitude <= 180
    ):
        raise ValueError("longitude must be a finite number between -180 and 180")
    offset = local.utcoffset().total_seconds() / 60
    eot = equation_of_time(local)
    longitude_minutes = longitude * 4 - offset
    total = longitude_minutes + eot
    clock = civil_clock + timedelta(minutes=total)
    distance = hour_boundary_distance(clock)
    return clock, {
        "version": VERSION,
        "basis": "apparent_solar",
        "applied": True,
        "civil_time": local.strftime("%Y-%m-%d %H:%M:%S %z"),
        "utc_instant": local.astimezone(timezone.utc).isoformat(),
        "clock_time": clock.strftime("%Y-%m-%d %H:%M:%S"),
        "longitude": longitude,
        "location": location or {},
        "utc_offset_minutes": offset,
        "dst_minutes": (local.dst() or timedelta()).total_seconds() / 60,
        "longitude_minutes": round(longitude_minutes, 6),
        "equation_of_time_minutes": round(eot, 6),
        "total_minutes": round(total, 6),
        "near_hour_boundary": distance <= 120,
        "boundary_distance_seconds": round(distance, 3),
        "formula": "真太阳钟 = 民用时钟 + (4×东经度 − 当时UTC偏移分钟数) + 均时差",
        "source": {
            "method": "NOAA/Meeus solar-coordinate equation of time approximation",
            "url": "https://gml.noaa.gov/grad/solcalc/calcdetails.html",
        },
        "notice": "均时差采用近似天文公式；城市中心坐标不能代替具体出生地址。太阳钟不附时区，年/月柱仍按原始物理时刻的节气确定。",
    }
