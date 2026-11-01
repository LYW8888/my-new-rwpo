import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server

class ServerRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = server.DB
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB = Path(cls.tmp.name) / "test.sqlite3"
        server.init_db()
    @classmethod
    def tearDownClass(cls):
        server.DB = cls.old
        cls.tmp.cleanup()
    def test_due_date_can_be_future_and_uses_default_time(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "parents":"沈", "place":"杭州", "date":"2099-04-16", "length":2, "gender":"unknown"})
        self.assertEqual(result["analysis"]["scenario"], "预产期起名")
        self.assertEqual(result["analysis"]["due_date"], "2099-04-16")
        self.assertEqual(result["analysis"]["due_time"], "12:00")
        self.assertTrue(result["analysis"]["bazi"]["reference"])
        self.assertTrue(result["candidates"])
    def test_surname_requires_one_or_two_han_characters(self):
        base = {"mode":"due_date", "dueDate":"2099-01-01", "place":"杭州"}
        for surname in ('A', '林😀', '张李王'):
            with self.subTest(surname=surname), self.assertRaisesRegex(ValueError, 'surname must'):
                server.analyze({**base, 'surname': surname})
        for surname in ('单', '欧阳', '𠮷'):
            with self.subTest(surname=surname):
                result = server.analyze({**base, 'surname': surname})
                self.assertTrue(result['candidates'][0]['name'].startswith(surname))
                self.assertEqual(len(result['candidates'][0]['pronunciation']['surname']), len(surname))
    def test_due_flow_rejects_actual_birth_instead_of_silently_switching(self):
        base = {"mode":"due_date", "surname":"林", "dueDate":"2099-04-20", "place":"杭州"}
        for extra in ({"birthDate":"2024-04-16"}, {"birthTime":"08:30"}, {"birthDate":"2024-04-16", "birthTime":"08:30"}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "due date flow"):
                server.analyze({**base, **extra})

    def test_born_flow_rejects_estimated_date(self):
        base = {"mode":"born", "surname":"林", "place":"杭州", "birthDate":"2024-02-10", "birthTime":"12:00"}
        with self.assertRaisesRegex(ValueError, "born flow"):
            server.analyze({**base, "dueDate":"2099-02-10"})
        value = server.analyze(base)["analysis"]
        self.assertIsNone(value["bazi_comparison"])
        self.assertEqual(value["due_date"], "")
        self.assertFalse(value["bazi"]["reference"])

    def test_each_flow_uses_only_its_explicit_clock(self):
        due = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2024-02-04", "dueTime":"16:27", "place":"杭州"})["analysis"]
        born = server.analyze({"mode":"born", "surname":"林", "birthDate":"2024-02-04", "birthTime":"16:27", "place":"杭州"})["analysis"]
        self.assertTrue(due["bazi"]["reference"])
        self.assertTrue(due["gua"]["reference"])
        self.assertTrue(due["bazi"]["boundary"])
        self.assertFalse(born["bazi"]["reference"])
        self.assertFalse(born["gua"]["reference"])
        self.assertEqual(due["bazi"]["pillars"], born["bazi"]["pillars"])
        self.assertNotEqual(due["workflow"]["id"], born["workflow"]["id"])

    def test_born_requires_actual_date_and_time(self):
        result = server.analyze({"mode":"born", "surname":"林", "birthDate":"2024-04-16", "birthTime":"08:30", "place":"杭州", "length":2, "gender":"male"})
        self.assertEqual(result["analysis"]["scenario"], "已出生起名")
        self.assertEqual(result["analysis"]["time"], "08:30")
    def test_missing_actual_time_is_rejected(self):
        with self.assertRaises(ValueError):
            server.analyze({"mode":"born", "surname":"林", "birthDate":"2024-04-16", "length":2, "gender":"unknown"})
    def test_future_actual_date_is_rejected(self):
        with self.assertRaises(ValueError):
            server.analyze({"mode":"born", "surname":"林", "birthDate":"2999-01-01", "birthTime":"08:30", "length":2, "gender":"female"})
    def test_invalid_due_time_is_rejected_but_future_due_date_is_valid(self):
        with self.assertRaisesRegex(ValueError, "dueTime"):
            server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "dueTime":"25:90", "place":"杭州", "length":2, "gender":"unknown"})
    def test_birth_time_rejects_offset_or_seconds(self):
        for invalid_time in ("12:00+08:00", "12:00:00"):
            with self.subTest(invalid_time=invalid_time):
                with self.assertRaisesRegex(ValueError, "birthTime"):
                    server.analyze({"mode":"born", "surname":"林", "birthDate":"2024-04-16", "birthTime":invalid_time, "place":"杭州", "length":2, "gender":"unknown"})
    def test_place_is_optional_and_civil_chart_does_not_guess_coordinates(self):
        base = {"surname":"林", "dueDate":"2099-01-01"}
        missing = server.analyze(base)
        supplied = server.analyze({**base, "place":"杭州"})
        self.assertEqual(missing["analysis"]["place"], "")
        self.assertFalse(missing["analysis"]["bazi"]["time_correction"]["applied"])
        self.assertEqual(missing["analysis"]["bazi"]["pillars"], supplied["analysis"]["bazi"]["pillars"])
        self.assertEqual(missing["candidates"], supplied["candidates"])

    def test_city_supplies_timezone_without_overriding_explicit_choice(self):
        base = {"surname":"林", "mode":"born", "birthDate":"1990-06-15", "birthTime":"12:00", "place":"臺北市"}
        inferred = server.analyze(base)["analysis"]
        explicit = server.analyze({**base, "zone":"Asia/Shanghai"})["analysis"]
        self.assertEqual(inferred["zone"], "Asia/Taipei")
        self.assertEqual(explicit["zone"], "Asia/Shanghai")
        self.assertIn("+0800", inferred["bazi"]["local_time"])
        self.assertIn("+0900", explicit["bazi"]["local_time"])
    def test_candidate_count_is_customizable_end_to_end(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":2, "candidateCount":5, "gender":"unknown"})
        self.assertEqual(result["analysis"]["candidate_count"], 5)
        self.assertEqual(result["analysis"]["available_candidate_count"], 30)
        self.assertEqual(len(result["candidates"]), 5)
    def test_candidate_count_range_is_validated(self):
        with self.assertRaisesRegex(ValueError, "candidateCount"):
            server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":2, "candidateCount":12, "gender":"unknown"})
    def test_candidate_count_reports_available_limit(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":3, "candidateCount":11, "gender":"unknown"})
        self.assertEqual(result["analysis"]["requested_candidate_count"], 11)
        self.assertEqual(result["analysis"]["candidate_count"], len(result["candidates"]))
        self.assertEqual(result["analysis"]["candidate_count"], 10)
        self.assertEqual(result["analysis"]["available_candidate_count"], 10)
        self.assertLess(result["analysis"]["candidate_count"], 11)
    def test_avoid_characters_are_hard_constraints_and_counts_are_honest(self):
        base = {"mode":"due_date", "surname":"安", "dueDate":"2099-01-01", "place":"杭州", "length":2, "candidateCount":11, "avoidedChars":"安、宁"}
        for variant in range(4):
            result = server.analyze({**base, "variant": variant})
            self.assertTrue(result["candidates"])
            self.assertEqual(len(result["candidates"]), min(11, result["analysis"]["available_candidate_count"]))
            for item in result["candidates"]:
                self.assertNotIn("安", item["given"])
                self.assertNotIn("宁", item["given"])
                self.assertTrue(item["name"].startswith("安"))  # Surname is not filtered.
    def test_no_matches_is_an_empty_result_not_a_different_length(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":1, "candidateCount":3, "avoidedChars":"安 澄 明 宁 远 知 衡 清 景 和 嘉 书 舒 川 若 桐 柏 煜 烨 培 均 钧 铭 沐 泽"})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["analysis"]["candidate_count"], 0)
        self.assertEqual(result["analysis"]["available_candidate_count"], 0)
    def test_explicit_and_legacy_character_preferences(self):
        base = {"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":2, "candidateCount":11}
        explicit = server.analyze({**base, "likedChars":"清", "avoidedChars":"安、宁"})
        legacy = server.analyze({**base, "chars":"喜欢‘清’，避开‘安、宁’"})
        self.assertEqual(explicit["candidates"], legacy["candidates"])
        self.assertTrue(any(item["given"] == "清晏" and any(c["id"] == "characters" and c["points"] > 0 for c in item["ranking"]["criteria"]) for item in explicit["candidates"]))
        with self.assertRaisesRegex(ValueError, "cannot overlap"):
            server.analyze({**base, "likedChars":"安", "avoidedChars":"安"})
        with self.assertRaisesRegex(ValueError, "avoidedChars must contain"):
            server.analyze({**base, "avoidedChars":"安 or 伟"})
    def test_rounds_explore_the_same_eligible_pool_without_inventing_evidence(self):
        base = {"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":2, "candidateCount":3, "avoidedChars":"安"}
        first = server.analyze(base)
        second = server.analyze({**base, "variant":1})
        self.assertTrue(set(item["given"] for item in first["candidates"]).isdisjoint(item["given"] for item in second["candidates"]))
        for item in first["candidates"] + second["candidates"]:
            self.assertNotIn("安", item["given"])
            self.assertIn(item["source_status"], ("pending", "demo"))
            self.assertIn("本次候选共用此时间起卦", item["gua_evidence"])
            self.assertTrue(item["pinyin"] and item["source"])
    def test_new_single_names_do_not_invent_classical_associations(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":1, "candidateCount":11, "likedChars":"知"})
        name = next(item for item in result["candidates"] if item["given"] == "知")
        self.assertIn("年月日时起卦", name["gua_evidence"])
        self.assertIn("按干支属性计算", name["yinyang_evidence"])
        self.assertIsNone(name["characters"][0]["element"])
        self.assertEqual(name["source_status"], "pending")
    def test_catalog_must_have_unique_names_and_no_unsubstantiated_verified_status(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            catalog = json.loads((server.DATA / "names.json").read_text(encoding="utf-8"))
            catalog["names"].append(catalog["names"][0])
            (data_dir / "names.json").write_text(json.dumps(catalog), encoding="utf-8")
            with patch.object(server, "DATA", data_dir), self.assertRaisesRegex(ValueError, "invalid record"):
                server.load_names()
            catalog["names"].pop()
            catalog["names"][0]["meaning_source"]["verification_status"] = "verified"
            (data_dir / "names.json").write_text(json.dumps(catalog), encoding="utf-8")
            with patch.object(server, "DATA", data_dir), self.assertRaisesRegex(ValueError, "invalid record"):
                server.load_names()
    def test_verified_source_requires_traceable_review_metadata(self):
        source = {"description": "测试义项", "verification_status": "verified", "reference": {
            "title": "测试词典", "edition": "测试版本", "citation": "测试条目", "url": "https://example.org/test",
            "license": "测试许可", "reviewed_by": "测试复核人", "reviewed_at": "2026-10-29"}}
        self.assertTrue(server.valid_source(source))
        source["reference"]["reviewed_at"] = "2026-02-30"
        self.assertFalse(server.valid_source(source))
        source["reference"]["reviewed_at"] = "2026-10-29"
        source["reference"]["url"] = "file:///test"
        self.assertFalse(server.valid_source(source))
    def test_rename_purpose_uses_born_flow_and_is_labeled(self):
        result = server.analyze({"purpose":"rename", "mode":"born", "surname":"林", "currentName":"林知远", "birthDate":"2024-04-16", "birthTime":"08:30", "place":"杭州", "length":2, "candidateCount":2, "gender":"unknown"})
        self.assertEqual(result["analysis"]["purpose"], "改名方案")
        self.assertEqual(result["analysis"]["scenario"], "改名 · 实际出生")
    def test_rename_purpose_rejects_due_date_flow(self):
        with self.assertRaisesRegex(ValueError, "rename purpose"):
            server.analyze({"purpose":"rename", "mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "length":2, "gender":"unknown"})
    def test_timezone_is_returned_and_included_in_method(self):
        result = server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "zone":"Asia/Taipei", "length":2, "gender":"unknown"})
        self.assertEqual(result["analysis"]["zone"], "Asia/Taipei")
        self.assertEqual(result["analysis"]["zone_label"], "台北时间 UTC+8")
        self.assertIn("台北时间", result["analysis"]["method"])
    def test_same_offset_timezone_names_have_same_pillars_and_candidates(self):
        base = {"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "dueTime":"12:00", "place":"杭州", "length":2, "gender":"unknown"}
        results = [server.analyze({**base, "zone": zone}) for zone in server.ZONE_LABELS]
        for result in results[1:]:
            self.assertEqual(result["analysis"]["bazi"]["pillars"], results[0]["analysis"]["bazi"]["pillars"])
            self.assertEqual(result["candidates"], results[0]["candidates"])
        self.assertTrue(results[0]["analysis"]["bazi"]["reference"])
    def test_timezone_is_validated(self):
        with self.assertRaisesRegex(ValueError, "zone"):
            server.analyze({"mode":"due_date", "surname":"林", "dueDate":"2099-01-01", "place":"杭州", "zone":"UTC", "length":2, "gender":"unknown"})
    def test_rename_keeps_current_name_as_context(self):
        result = server.analyze({"purpose":"rename", "mode":"born", "surname":"林", "currentName":"林知远", "birthDate":"2024-04-16", "birthTime":"08:30", "place":"杭州", "length":2, "gender":"unknown"})
        self.assertEqual(result["analysis"]["current_name"], "林知远")
        self.assertFalse(result["analysis"]["bazi"]["reference"])
    def test_current_name_length_is_validated(self):
        with self.assertRaisesRegex(ValueError, "currentName"):
            server.analyze({"purpose":"rename", "mode":"born", "surname":"林", "currentName":"名" * 21, "birthDate":"2024-04-16", "birthTime":"08:30", "place":"杭州", "length":2, "gender":"unknown"})
    def test_same_day_future_birth_time_is_rejected(self):
        class FrozenDateTime(server.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 4, 16, 10, 0, tzinfo=tz)
        with patch.object(server, "datetime", FrozenDateTime):
            with self.assertRaisesRegex(ValueError, "birthTime cannot"):
                server.analyze({"mode":"born", "surname":"林", "birthDate":"2026-04-16", "birthTime":"10:01", "place":"杭州", "length":2, "gender":"unknown"})

if __name__ == "__main__":
    unittest.main()
