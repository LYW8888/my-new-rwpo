import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import solar_time
import bazi
import server


class SolarTimeTest(unittest.TestCase):
    def test_known_seasonal_eot_samples(self):
        # JPL apparent solar RA/GAST/UT1 independently gives about -14.19 and +16.45 minutes.
        for date, expected in [
            ("2024-02-11", -14.193),
            ("2024-11-03", 16.451),
            ("2024-04-15", 0.086),
        ]:
            instant = datetime.fromisoformat(date + "T12:00:00+00:00")
            self.assertAlmostEqual(solar_time.equation_of_time(instant), expected, delta=0.1)
        with self.assertRaisesRegex(ValueError, "aware"):
            solar_time.equation_of_time(datetime(2024, 1, 1))

    def test_longitude_slope_and_timezone_invariance(self):
        instant = datetime(2024, 2, 10, 4, tzinfo=timezone.utc)
        local = instant.astimezone(ZoneInfo("Asia/Shanghai"))
        a, meta = solar_time.correct(local, "apparent_solar", 120)
        b, _ = solar_time.correct(local, "apparent_solar", 121)
        utc_clock, _ = solar_time.correct(instant, "apparent_solar", 120)
        self.assertEqual((b - a).total_seconds(), 240)
        self.assertEqual(a, utc_clock)
        self.assertAlmostEqual(
            meta["total_minutes"],
            meta["longitude_minutes"] + meta["equation_of_time_minutes"],
            places=5,
        )

    def test_historical_dst_is_included_once(self):
        local = datetime(1991, 7, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        clock, meta = solar_time.correct(local, "apparent_solar", 120)
        utc_clock, _ = solar_time.correct(local.astimezone(timezone.utc), "apparent_solar", 120)
        self.assertEqual(clock, utc_clock)
        self.assertEqual(meta["utc_offset_minutes"], 540)
        self.assertEqual(meta["dst_minutes"], 60)
        self.assertEqual(meta["longitude_minutes"], -60)

    def test_solar_day_rollover_and_civil_pillars_preserved(self):
        civil = bazi.calculate("2024-02-10", "23:05", "Asia/Shanghai")
        west = bazi.calculate(
            "2024-02-10", "23:05", "Asia/Shanghai", time_basis="apparent_solar", longitude=75.99
        )
        self.assertEqual(west["civil_pillars"], civil["pillars"])
        self.assertEqual(west["pillars"][2]["ganzhi"], "甲辰")
        self.assertEqual(civil["pillars"][2]["ganzhi"], "乙巳")
        self.assertIn("日柱", west["time_correction"]["pillar_changes"])
        east = bazi.calculate(
            "2024-02-10", "22:55", "Asia/Shanghai", time_basis="apparent_solar", longitude=140
        )
        self.assertTrue(east["time_correction"]["clock_time"].startswith("2024-02-11"))
        self.assertEqual(east["pillars"][2]["ganzhi"], "乙巳")

    def test_solar_correction_does_not_move_physical_solar_terms(self):
        civil = bazi.calculate("2024-02-04", "16:30", "Asia/Shanghai")
        west = bazi.calculate(
            "2024-02-04", "16:30", "Asia/Shanghai", time_basis="apparent_solar", longitude=87.62
        )
        self.assertLess(west["time_correction"]["clock_time"][11:16], "16:27")
        self.assertEqual(west["pillars"][:2], civil["pillars"][:2])
        self.assertEqual([p["ganzhi"] for p in west["pillars"][:2]], ["甲辰", "丙寅"])
        self.assertEqual(west["previous_jie"], civil["previous_jie"])

    def test_near_hour_boundary_is_explicit(self):
        local = datetime(2024, 2, 10, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        longitude = (480 - solar_time.equation_of_time(local) - 60) / 4
        _, value = solar_time.correct(local, "apparent_solar", longitude)
        self.assertTrue(value["near_hour_boundary"])
        self.assertLess(value["boundary_distance_seconds"], 0.1)

    def test_city_centre_and_manual_override_are_distinguished(self):
        city = solar_time.options({"timeBasis": "apparent_solar", "locationId": "hangzhou"})
        self.assertEqual(city["longitude"], 120.16)
        self.assertEqual(city["location"]["coordinate_source"], "city_centre")
        manual = solar_time.options(
            {"timeBasis": "apparent_solar", "locationId": "hangzhou", "longitude": "120.15"}
        )
        self.assertEqual(manual["longitude"], 120.15)
        self.assertEqual(manual["location"]["coordinate_source"], "manual")
        self.assertEqual(solar_time.options({"longitude": 0})["longitude"], 0)

    def test_invalid_coordinates_and_missing_location_are_not_guessed(self):
        with self.assertRaisesRegex(ValueError, "longitude is required"):
            solar_time.options({"timeBasis": "apparent_solar", "place": "未收录的城市"})
        for value in (True, "NaN", "Infinity", 181, -181, {}, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "longitude must"):
                solar_time.options({"timeBasis": "apparent_solar", "longitude": value})
        with self.assertRaisesRegex(ValueError, "locationId"):
            solar_time.options({"locationId": "not-listed"})
        with self.assertRaisesRegex(ValueError, "timeBasis"):
            solar_time.options({"timeBasis": "guess"})

    def test_birth_city_matches_listed_names_and_safe_aliases(self):
        for place, identifier in (("杭州", "hangzhou"), (" 杭州市 ", "hangzhou"), ("臺北市", "taipei"), ("乌鲁木齐市", "urumqi")):
            with self.subTest(place=place):
                result = solar_time.options({"timeBasis":"apparent_solar", "place":place})
                self.assertEqual(result["location"]["id"], identifier)
                self.assertEqual(result["location"]["coordinate_source"], "city_centre")
        for place in ("", "杭州附近", "杭州市西湖区", "河南南阳"):
            self.assertIsNone(solar_time.find_city(place))

    def test_conflicting_city_identifier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "locationId conflicts"):
            solar_time.options({"timeBasis":"apparent_solar", "place":"杭州", "locationId":"chengdu"})

    def test_manual_coordinates_override_matched_city_and_allow_missing_label(self):
        manual = solar_time.options({"timeBasis":"apparent_solar", "place":"杭州", "longitude":"120.15"})
        self.assertEqual(manual["longitude"], 120.15)
        self.assertEqual(manual["location"]["coordinate_source"], "manual")
        zero = server.analyze({"surname":"林", "dueDate":"2099-01-01", "timeBasis":"apparent_solar", "longitude":0})["analysis"]
        self.assertEqual(zero["bazi"]["time_correction"]["longitude"], 0)
        self.assertEqual(zero["bazi"]["time_correction"]["location"]["coordinate_source"], "manual")

    def test_birth_city_changes_solar_clock_and_downstream_hour(self):
        base = {"surname":"林", "mode":"born", "birthDate":"2024-02-10", "birthTime":"12:00", "timeBasis":"apparent_solar"}
        east = server.analyze({**base, "place":"杭州"})["analysis"]
        west = server.analyze({**base, "place":"成都"})["analysis"]
        a, b = east["bazi"]["time_correction"], west["bazi"]["time_correction"]
        self.assertAlmostEqual(a["total_minutes"] - b["total_minutes"], (120.16 - 104.07) * 4, places=5)
        self.assertNotEqual(east["bazi"]["pillars"][3], west["bazi"]["pillars"][3])
        self.assertNotEqual(east["gua"]["inputs"]["hour_branch"], west["gua"]["inputs"]["hour_branch"])
        self.assertEqual(east["bazi"]["pillars"][:2], west["bazi"]["pillars"][:2])

    def test_api_uses_actual_time_for_solar_chart_and_gua(self):
        base = {
            "surname": "林",
            "place": "杭州",
            "mode": "born",
            "birthDate": "2024-02-10",
            "birthTime": "23:05",
            "timeBasis": "apparent_solar",
            "longitude": 75.99,
        }
        actual = server.analyze(base)
        with self.assertRaisesRegex(ValueError, "due date flow"):
            server.analyze({**base, "mode":"due_date", "dueDate":"2099-12-23"})
        self.assertEqual(actual["analysis"]["gua"]["clock_basis"], "apparent_solar")
        self.assertEqual(actual["analysis"]["gua"]["inputs"]["hour_branch"], "戌")
        self.assertTrue(actual["analysis"]["bazi"]["time_correction"]["applied"])

    def test_default_civil_mode_and_supported_year_edges(self):
        for date, time in [("1900-01-01", "00:01"), ("2100-12-31", "23:59")]:
            chart = bazi.calculate(
                date, time, "Asia/Shanghai", time_basis="apparent_solar", longitude=-180
            )
            self.assertEqual(len(chart["pillars"]), 4)
        civil = bazi.calculate("2024-02-10", "12:00", "Asia/Shanghai")
        self.assertFalse(civil["time_correction"]["applied"])
        self.assertEqual(civil["civil_pillars"], civil["pillars"])
        edge = bazi.calculate("2024-02-10", "23:00", "Asia/Shanghai")
        self.assertTrue(edge["time_correction"]["near_hour_boundary"])
