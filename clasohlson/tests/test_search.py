"""Offline checks for the dependency-free search client."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location(
    "search", Path(__file__).parents[1] / "scripts" / "search.py"
)
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


class SearchTests(unittest.TestCase):
    def test_success_and_request_parameters(self):
        response = io.BytesIO(b'{"panels": []}')
        with patch.object(search.urllib.request, "urlopen", return_value=response) as open_url:
            self.assertEqual(search.search_products("led ää", limit=3, offset=4), {"panels": []})
        request = open_url.call_args.args[0]
        params = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(params["esales.searchPhrase"], ["led ää"])
        self.assertEqual(params["window_first"], ["4"])
        self.assertEqual(params["window_last"], ["6"])
        self.assertIn("&search_attributes=name_fi,baseprice,", request.full_url)
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 15})
        self.assertTrue(response.closed)

    def test_http_400_keeps_product_data(self):
        body = io.BytesIO(b'{"panels": [{"name": "product-suggestions", "products": '
                          b'[{"variants": [{"key": "123_FI", "attributes": '
                          b'{"name_fi": ["Example product"]}}]}]}]}')
        error = HTTPError("https://example.org/", 400, "Bad Request", {}, body)
        with patch.object(search.urllib.request, "urlopen", side_effect=error):
            products = search.extract_products(search.search_products("example"))
        self.assertEqual(products, [{"key": "123_FI", "name_fi": "Example product"}])
        self.assertTrue(body.closed)

    def test_other_http_errors_propagate_and_close(self):
        for code in (401, 404, 500, 503):
            with self.subTest(code=code):
                body = io.BytesIO(b'{}')
                error = HTTPError("https://example.org/", code, "error", {}, body)
                with patch.object(search.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(HTTPError) as caught:
                        search.search_products("example")
                self.assertIs(caught.exception, error)
                self.assertTrue(body.closed)

    def test_invalid_json_and_connection_errors_propagate(self):
        with patch.object(search.urllib.request, "urlopen", return_value=io.BytesIO(b'invalid')):
            with self.assertRaises(json.JSONDecodeError):
                search.search_products("example")
        with patch.object(search.urllib.request, "urlopen", side_effect=URLError("offline")):
            with self.assertRaises(URLError):
                search.search_products("example")

    def test_json_cli(self):
        with patch("sys.argv", ["search.py", "example", "--json"]), \
             patch.object(search.urllib.request, "urlopen", return_value=io.BytesIO(b'{"panels": []}')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            search.main()
        self.assertEqual(json.loads(output.getvalue()), {"panels": []})


if __name__ == "__main__":
    unittest.main()
