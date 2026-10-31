"""accountimagemaker のテスト（Flask テストクライアント経由、実ネットワークなし）。"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_dimensions(data: bytes) -> tuple[int, int]:
    """PNG の IHDR から幅・高さを読む。"""
    if data[:8] != PNG_SIGNATURE:
        raise AssertionError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class AccountImageMakerTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def get_img(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.client.get(f"/img?{query}")

    def test_index_ok(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/img?seed=", resp.data)
        # 候補が6件表示される
        self.assertEqual(resp.data.count(b"/img?seed="), 12)  # 表示用+DLリンクで各2回

    def test_index_invalid_params_fallback(self):
        resp = self.client.get("/?style=banana&size=abc")
        self.assertEqual(resp.status_code, 200)

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})

    def test_img_returns_png(self):
        resp = self.get_img(seed=42, style="identicon", size=256)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.startswith(PNG_SIGNATURE))

    def test_img_reproducible_same_seed(self):
        a = self.get_img(seed=1234, style="geometric", size=256).data
        b = self.get_img(seed=1234, style="geometric", size=256).data
        self.assertEqual(a, b)

    def test_img_differs_by_seed(self):
        a = self.get_img(seed=1, style="identicon", size=256).data
        b = self.get_img(seed=2, style="identicon", size=256).data
        self.assertNotEqual(a, b)

    def test_all_styles(self):
        for style in ("identicon", "geometric", "pixel"):
            resp = self.get_img(seed=7, style=style, size=256)
            self.assertEqual(resp.status_code, 200, style)
            self.assertTrue(resp.data.startswith(PNG_SIGNATURE), style)

    def test_size_reflected_in_png(self):
        for size in (256, 512, 1024):
            resp = self.get_img(seed=99, style="pixel", size=size)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(png_dimensions(resp.data), (size, size))

    def test_invalid_params_not_500(self):
        cases = [
            {"seed": 1, "style": "banana", "size": 256},
            {"seed": 1, "style": "identicon", "size": "abc"},
            {"seed": 1, "style": "identicon", "size": 123},
            {"seed": "xyz", "style": "identicon", "size": 256},
        ]
        for params in cases:
            resp = self.get_img(**params)
            self.assertEqual(resp.status_code, 400, params)

    def test_download_header(self):
        resp = self.get_img(seed=5, style="identicon", size=256, download=1)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()
