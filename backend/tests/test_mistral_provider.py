"""Tests for the Mistral AI provider integration in services/agents/_base.py."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.agents._base import _mistral_content_text, _mistral_error

class TestMistralContentText(unittest.TestCase):
    """_mistral_content_text must handle both string and list-of-blocks content."""

    def test_plain_string(self):
        self.assertEqual(_mistral_content_text("hello world"), "hello world")

    def test_list_with_thinking_and_text_blocks(self):
        content = [
            {"type": "thinking", "thinking": [{"type": "text", "text": "reasoning..."}]},
            {"type": "text", "text": "The answer is 42."},
            {"type": "text", "text": "Hope that helps."},
        ]
        self.assertEqual(_mistral_content_text(content), "The answer is 42. Hope that helps.")

    def test_list_text_only(self):
        content = [{"type": "text", "text": "just text"}]
        self.assertEqual(_mistral_content_text(content), "just text")

    def test_empty_list(self):
        self.assertEqual(_mistral_content_text([]), "")

    def test_none(self):
        self.assertEqual(_mistral_content_text(None), "")

    def test_only_thinking_blocks(self):
        content = [{"type": "thinking", "thinking": [{"type": "text", "text": "hmm"}]}]
        self.assertEqual(_mistral_content_text(content), "")

    def test_mixed_unknown_block_types_ignored(self):
        content = [
            {"type": "tool_call", "id": "abc"},
            {"type": "text", "text": "result"},
        ]
        self.assertEqual(_mistral_content_text(content), "result")


class TestMistralError(unittest.TestCase):

    def _resp(self, status_code: int, body: dict) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = body
        return r

    def test_401_auth(self):
        r = self._resp(401, {"message": "Unauthorized"})
        self.assertIn("invalid or missing", _mistral_error(r))

    def test_429_rate_limit(self):
        r = self._resp(429, {"message": "Too many requests"})
        self.assertIn("rate limit", _mistral_error(r))

    def test_500_server(self):
        r = self._resp(500, {"message": "Internal error"})
        self.assertIn("temporarily unavailable", _mistral_error(r))

    def test_generic_message(self):
        r = self._resp(400, {"message": "bad request details"})
        self.assertIn("bad request details", _mistral_error(r))

    def test_non_json_body(self):
        r = MagicMock()
        r.status_code = 502
        r.json.side_effect = Exception("not json")
        self.assertIn("502", _mistral_error(r))


class TestMistralRunnersContentHandling(unittest.IsolatedAsyncioTestCase):
    """Verify _run_mistral_model and _run_mistral_chat handle list-content responses."""

    @patch("services.agents._base.httpx.AsyncClient")
    async def test_run_mistral_chat_extracts_text_from_blocks(self, mock_client_cls):
        from services.agents._base import _run_mistral_chat
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": []},
                        {"type": "text", "text": "Portfolio looks healthy."},
                    ]
                }
            }]
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        result = await _run_mistral_chat(
            messages=[{"role": "user", "content": "hi"}],
            system="sys", model="mistral-large-latest", api_key="test-key-123456", max_tokens=100,
        )
        self.assertEqual(result, "Portfolio looks healthy.")

    @patch("services.agents._base.httpx.AsyncClient")
    async def test_run_mistral_model_extracts_json_from_blocks(self, mock_client_cls):
        from services.agents._base import _run_mistral_model
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": []},
                        {"type": "text", "text": '{"score": 75, "trend": "BULLISH"}'},
                    ]
                }
            }]
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        result = await _run_mistral_model(
            system="sys", user_msg="analyze", model="ministral-8b-latest",
            api_key="test-key-123456", max_tokens=100,
        )
        self.assertEqual(result, {"score": 75, "trend": "BULLISH"})


if __name__ == "__main__":
    unittest.main()
