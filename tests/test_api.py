import base64
import http.client
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.server import create_server

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "draft_001.png"


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, port = create_server(port=0)
        cls.port = port
        cls.base = "http://127.0.0.1:%d" % port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def _request(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_status(self):
        status, data = self._request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["schools"], 13)
        self.assertGreaterEqual(data["guides"], 8)

    def test_sample_and_recommend(self):
        status, sample = self._request("POST", "/api/sample", {})
        self.assertEqual(status, 200)
        self.assertEqual([h["name"] for h in sample["heroes"]], ["森林游侠", "神秘法师", "魔镜"])
        payload = {
            "heroes": [h["name"] for h in sample["heroes"]],
            "enabled": [s["id"] for s in sample["schools"]["enabled"]],
            "banned": [s["id"] for s in sample["schools"]["banned"]],
        }
        status, rec = self._request("POST", "/api/recommend", payload)
        self.assertEqual(status, 200)
        self.assertEqual(rec["recommendations"][0]["name"], "神秘法师")
        self.assertEqual(len(rec["recommendations"][0]["evidence"]), 3)

    def test_analyze_base64(self):
        raw = base64.b64encode(SAMPLE.read_bytes()).decode("ascii")
        status, data = self._request("POST", "/api/analyze", {"image": "data:image/png;base64," + raw})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["schools"]["enabled"]), 8)
        self.assertTrue(data["image"]["preview"].startswith("data:image/jpeg;base64,"))

    def test_recommend_validation(self):
        status, data = self._request("POST", "/api/recommend", {"heroes": ["神秘法师"], "enabled": ["basic"]})
        self.assertEqual(status, 400)
        self.assertIn("8", data["error"])

    def test_static_index(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as resp:
            body = resp.read().decode("utf-8")
        self.assertIn("选技大乱斗", body)
        self.assertIn("/static/app.js", body)
        self.assertIn("/library", body)

    def test_library_page_and_data(self):
        with urllib.request.urlopen(self.base + "/library", timeout=10) as resp:
            body = resp.read().decode("utf-8")
        self.assertIn("英雄图鉴", body)
        self.assertIn("/static/library.js", body)

        status, data = self._request("GET", "/api/heroes")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["heroes"]), 60)
        self.assertEqual(len(data["schools"]), 13)
        self.assertEqual(data["meta"]["cards"], 156)
        hero = next(h for h in data["heroes"] if h["name"] == "神秘法师")
        self.assertTrue(hero["core_cards"])
        self.assertEqual(len(hero["stats"]), 6)
        self.assertTrue(hero["art"].startswith("/data/art/heroes/"))
        self.assertTrue(hero["talent_icon"].startswith("/data/art/skills/"))

        with urllib.request.urlopen(self.base + hero["art"], timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "image/png")

        status, cards = self._request("GET", "/api/cards")
        self.assertEqual(status, 200)
        self.assertEqual(len(cards["cards"]), 156)
        self.assertTrue(cards["cards"][0]["desc"])

        status, rules = self._request("GET", "/api/rules")
        self.assertEqual(status, 200)
        self.assertTrue(rules["rules"]["attributes"])

    def test_overlay_trigger_requires_agent(self):
        import app.server as server

        previous = server.OVERLAY_TRIGGER
        try:
            server.OVERLAY_TRIGGER = None
            status, data = self._request("POST", "/api/overlay/capture", {})
            self.assertEqual(status, 400)
            self.assertIn("浮窗", data["error"])

            calls = []
            server.OVERLAY_TRIGGER = lambda: calls.append(1)
            status, data = self._request("POST", "/api/overlay/capture", {})
            self.assertEqual(status, 200)
            self.assertTrue(data["ok"])
            self.assertEqual(calls, [1])
        finally:
            server.OVERLAY_TRIGGER = previous

    def test_keep_alive_body_drain(self):
        """A POST with an ignored body must not poison the next request."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request("POST", "/api/sample", body=b"{}", headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            sample = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(len(sample["heroes"]), 3)

            payload = json.dumps(
                {
                    "heroes": [h["name"] for h in sample["heroes"]],
                    "enabled": [s["id"] for s in sample["schools"]["enabled"]],
                    "banned": [s["id"] for s in sample["schools"]["banned"]],
                }
            ).encode("utf-8")
            conn.request("POST", "/api/recommend", body=payload, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(data["recommendations"][0]["name"], "神秘法师")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
