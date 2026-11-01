import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from sonos_app.sonos_client import SonosAPIError, SonosClient, SonosReauthorizationRequired
from sonos_app.token import SonosToken


class SonosClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.token = SonosToken("access-token", "refresh-token")
        self.store = Mock()
        self.store.load_tokens.return_value = self.token
        self.client = SonosClient(self.token, self.store, Mock())

    async def request(self, method, responses):
        self.requests = []

        def handle(request):
            self.requests.append(request)
            return responses.pop(0)

        transport = httpx.MockTransport(handle)
        client_factory = httpx.AsyncClient
        with patch("sonos_app.sonos_client.httpx.AsyncClient", side_effect=lambda **kwargs: client_factory(
            transport=transport, **kwargs
        )):
            return await getattr(self.client, method)("https://sonos.test/resource")

    async def test_get_and_post_expose_structured_errors(self):
        for method in ("_get_json", "_post_json"):
            with self.subTest(method=method):
                with self.assertRaises(SonosAPIError) as raised:
                    await self.request(method, [httpx.Response(410, json={"errorCode": "ERROR_RESOURCE_GONE"})])
                self.assertEqual(raised.exception.status_code, 410)
                self.assertEqual(raised.exception.error_code, "ERROR_RESOURCE_GONE")
                self.assertIn("Sonos API error 410", str(raised.exception))
                self.assertEqual(len(self.requests), 1)

    async def test_non_json_and_unexpected_error_bodies_preserve_the_status(self):
        for method in ("_get_json", "_post_json"):
            for body in ("", "unavailable", "[]", "null", '{"errorCode": 123}'):
                with self.subTest(method=method, body=body):
                    with self.assertRaises(SonosAPIError) as raised:
                        await self.request(method, [httpx.Response(503, text=body)])
                    self.assertEqual(raised.exception.status_code, 503)
                    self.assertIsNone(raised.exception.error_code)

    async def test_error_after_token_refresh_is_still_structured(self):
        for method in ("_get_json", "_post_json"):
            with self.subTest(method=method), patch.object(self.client, "_refresh_access_token", new_callable=AsyncMock) as refresh:
                with self.assertRaises(SonosAPIError) as raised:
                    await self.request(method, [
                        httpx.Response(401),
                        httpx.Response(410, json={"errorCode": "ERROR_RESOURCE_GONE"}),
                    ])
                self.assertEqual(raised.exception.status_code, 410)
                refresh.assert_awaited_once()
                self.assertEqual(len(self.requests), 2)

    async def test_rejected_refreshed_token_still_requires_reauthorization(self):
        for method in ("_get_json", "_post_json"):
            with self.subTest(method=method), patch.object(self.client, "_refresh_access_token", new_callable=AsyncMock):
                with self.assertRaises(SonosReauthorizationRequired):
                    await self.request(method, [httpx.Response(401), httpx.Response(401)])

    async def test_successful_responses_are_unchanged(self):
        self.assertEqual(await self.request("_get_json", [httpx.Response(200, json={"groups": []})]), {"groups": []})
        self.assertEqual(await self.request("_post_json", [httpx.Response(200)]), {})
