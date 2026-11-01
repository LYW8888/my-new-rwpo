"""Exercise public routes and malformed requests against a real HTTP server."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import server


class HttpHandlerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_db = server.DB
        cls.old_dist = server.DIST
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB = Path(cls.tmp.name) / 'test.sqlite3'
        server.DIST = Path(cls.tmp.name) / 'dist'
        (server.DIST / 'assets').mkdir(parents=True)
        (server.DIST / 'index.html').write_text('<div id="root"></div>', encoding='utf-8')
        (server.DIST / 'service-worker.js').write_text('// test', encoding='utf-8')
        (server.DIST / 'manifest.webmanifest').write_text('{}', encoding='utf-8')
        (server.DIST / 'favicon.svg').write_text('<svg/>', encoding='utf-8')
        (server.DIST / 'assets' / 'index-abc123.js').write_text('// built asset', encoding='utf-8')
        server.init_db()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        server.DB = cls.old_db
        server.DIST = cls.old_dist
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_public_assets_and_apis_are_available(self):
        for path in sorted(server.PUBLIC_ASSETS):
            with self.subTest(path=path):
                status, headers, body = self.request('GET', path + '?v=1')
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn('no-store', headers['Cache-Control'])
        for path in ('/api/health', '/api/catalog', '/api/classics', '/api/product', '/api/name-counts'):
            with self.subTest(path=path):
                status, _, body = self.request('GET', path)
                self.assertEqual(status, 200)
                json.loads(body)

    def test_private_files_and_path_aliases_are_not_served(self):
        for method in ('GET', 'HEAD'):
            for path in ('/data/', '/data/naming.sqlite3', '/.git/config', '/server.py', '/phonetics.py',
                         '/tests/test_server.py', '/README.md', '/operations/console.py', '/operations/', '/backoffice/settings.py', '/customer/settings.py', '/admin.html', '/data/../server.py',
                         '/data/%2e%2e/server.py', '/%2e%67it/config', '/frontend/package.json',
                         '/assets/../index.html', '/assets/%2e%2e/index.html'):
                with self.subTest(method=method, path=path):
                    status, _, _ = self.request(method, path)
                    self.assertEqual(status, 404)

    def test_customer_capability_stub_does_not_authenticate_or_issue_cookies(self):
        status, headers, body = self.request('GET', '/api/customer/session', headers={'Cookie':'__Secure-xuming_customer=staff-or-customer-session'})
        self.assertEqual(status,200)
        self.assertIsNone(json.loads(body)['customer'])
        self.assertFalse(json.loads(body)['sms_available'])
        self.assertNotIn('Set-Cookie',headers)

    def test_built_assets_and_missing_build_behavior(self):
        status, _, body = self.request('GET', '/assets/index-abc123.js')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'// built asset')
        outside = Path(self.tmp.name) / 'secret.js'
        outside.write_text('private', encoding='utf-8')
        (server.DIST / 'assets' / 'leak.js').symlink_to(outside)
        self.assertEqual(self.request('GET', '/assets/leak.js')[0], 404)
        from unittest.mock import patch
        with patch.object(server, 'DIST', Path(self.tmp.name) / 'missing'):
            self.assertEqual(self.request('GET', '/')[0], 503)
            self.assertEqual(self.request('GET', '/api/health')[0], 200)

    def test_analyze_is_not_cached_and_handles_invalid_bodies(self):
        valid = {'mode': 'due_date', 'surname': '林', 'dueDate': '2099-01-01',
                 'place': '杭州', 'length': 2, 'gender': 'unknown'}
        status, headers, body = self.request('POST', '/api/analyze', json.dumps(valid), {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertIn('no-store', headers['Cache-Control'])
        data = json.loads(body)
        self.assertEqual(len(data['analysis']['bazi']['pillars']), 4)
        self.assertEqual(data['candidates'][0]['pronunciation']['source']['library'], 'pypinyin')
        for raw in (b'[]', b'null', b'{', json.dumps({**valid, 'styles': [{}]}).encode()):
            with self.subTest(body=raw):
                status, _, body = self.request('POST', '/api/analyze', raw, {'Content-Type': 'application/json'})
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(body))
        for length in ('-1', str(65537), 'invalid'):
            with self.subTest(length=length):
                status, _, body = self.request('POST', '/api/analyze', b'', {'Content-Length': length})
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(body))

    def test_name_review_is_uncached_validated_and_distinct_from_recommendations(self):
        payload = {"purpose":"rename", "mode":"born", "surname":"李", "currentName":"李景和", "birthDate":"1998-08-13", "birthTime":"13:48", "place":"河南南阳"}
        status, headers, body = self.request('POST', '/api/name-review', json.dumps(payload), {'Content-Type':'application/json'})
        self.assertEqual(status,200)
        self.assertIn('no-store',headers['Cache-Control'])
        value = json.loads(body)
        self.assertEqual(value['candidates'],[])
        self.assertEqual(value['analysis']['name_review']['full_name'],'李景和')
        for data in ({**payload,'currentName':''},{**payload,'purpose':'newborn'},{**payload,'dueDate':'2099-01-01'}):
            with self.subTest(data=data):
                status, _, _ = self.request('POST','/api/name-review',json.dumps(data),{'Content-Type':'application/json'})
                self.assertEqual(status,400)

    def test_literary_profile_reference_metadata_and_private_raw_files(self):
        status,_,body=self.request('GET','/api/naming-corpus')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['character_records'],3636)
        status,_,body=self.request('GET','/api/name-counts?algorithm=literary_v3')
        self.assertEqual(status,200)
        self.assertGreater(json.loads(body)['counts']['2'],65)
        for path in ('/data/naming/raw/诗经.txt','/data/naming-corpus.sqlite3','/data/naming/rules.json'):
            self.assertEqual(self.request('GET',__import__('urllib.parse',fromlist=['quote']).quote(path,safe='/'))[0],404)
        self.assertEqual(self.request('GET','/api/name-counts?algorithm=unknown')[0],400)

    def test_selected_surname_readings_and_literary_constraints(self):
        from urllib.parse import quote
        status,_,body=self.request('GET','/api/surname-readings?surname='+quote('单'))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['default'],'shàn')
        data={'algorithm':'literary_v3','surname':'李','mode':'due_date','dueDate':'2099-01-01','place':'杭州','requiredChars':'安','candidateCount':7}
        status,headers,body=self.request('POST','/api/analyze',json.dumps(data),{'Content-Type':'application/json'})
        self.assertEqual(status,200)
        self.assertIn('no-store',headers['Cache-Control'])
        response=json.loads(body)
        self.assertEqual(len(response['candidates']),7)
        self.assertTrue(all('安' in x['given'] for x in response['candidates']))

    def test_optional_birth_city_and_automatic_solar_coordinates(self):
        base = {'surname':'林', 'mode':'due_date', 'dueDate':'2099-01-01'}
        for extra, applied in (({}, False), ({'place':'臺北市', 'timeBasis':'apparent_solar'}, True)):
            with self.subTest(extra=extra):
                status, _, body = self.request('POST', '/api/analyze', json.dumps({**base, **extra}), {'Content-Type':'application/json'})
                self.assertEqual(status, 200)
                analysis = json.loads(body)['analysis']
                self.assertEqual(analysis['bazi']['time_correction']['applied'], applied)
                if applied:
                    self.assertEqual(analysis['zone'], 'Asia/Taipei')
                    self.assertEqual(analysis['bazi']['time_correction']['longitude'], 121.57)
