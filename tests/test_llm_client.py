import json
from unittest.mock import MagicMock, patch


from rathausrot.llm_client import OpenRouterClient


def make_client(**overrides):
    config = {
        "openrouter": {
            "api_key": "test-key",
            "model": "test-model",
            "max_tokens": 100,
            "system_prompt": "",
        },
        "bot": {"party": "TestPartei"},
    }
    config.update(overrides)
    return OpenRouterClient(config)


class TestDictToResult:
    def test_normal_values(self):
        client = make_client()
        data = {
            "summary": "A summary",
            "key_points": ["kp1", "kp2"],
            "verdict": "Zustimmung",
            "verdict_reason": "Good reasons",
            "relevance_score": 4,
        }
        result = client._dict_to_result(data)
        assert result.summary == "A summary"
        assert result.verdict == "Zustimmung"
        assert result.relevance_score == 4

    def test_string_relevance_score_fallback(self):
        client = make_client()
        data = {"summary": "test", "relevance_score": "3/5"}
        result = client._dict_to_result(data)
        assert result.relevance_score == 3  # default fallback

    def test_relevance_score_clamped(self):
        client = make_client()
        result = client._dict_to_result({"summary": "test", "relevance_score": 10})
        assert result.relevance_score == 5
        result = client._dict_to_result({"summary": "test", "relevance_score": -1})
        assert result.relevance_score == 1

    def test_missing_fields_use_defaults(self):
        client = make_client()
        result = client._dict_to_result({})
        assert result.summary == ""
        assert result.verdict == "Enthaltung"
        assert result.relevance_score == 3


class TestParseResponse:
    def test_direct_json(self):
        client = make_client()
        data = {"summary": "Test", "verdict": "Ablehnung", "relevance_score": 2}
        result = client._parse_response(json.dumps(data))
        assert result.summary == "Test"
        assert result.verdict == "Ablehnung"

    def test_json_in_code_block(self):
        client = make_client()
        text = 'Here is the analysis:\n```json\n{"summary": "Block", "verdict": "Zustimmung"}\n```\nDone.'
        result = client._parse_response(text)
        assert result.summary == "Block"

    def test_balanced_brace_extraction(self):
        client = make_client()
        text = 'Prefix text {"summary": "Balanced", "nested": {"a": 1}} suffix text'
        result = client._parse_response(text)
        assert result.summary == "Balanced"

    def test_unparseable_returns_default(self):
        client = make_client()
        result = client._parse_response("This is not JSON at all")
        assert result.summary.startswith("This is not JSON")

    def test_greedy_regex_avoided(self):
        client = make_client()
        # Two JSON objects - should only match the first complete one
        text = '{"summary": "First"} some text {"summary": "Second"}'
        result = client._parse_response(text)
        assert result.summary == "First"


class TestComplete:
    def test_successful_response(self):
        client = make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "test content"}}],
            "usage": {"total_tokens": 42},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            result, tokens = client._complete("system", "user")
        assert result == "test content"
        assert tokens == 42

    def test_malformed_response_retries(self):
        client = make_client()
        bad_resp = MagicMock()
        bad_resp.json.return_value = {"error": "bad"}  # no choices key
        bad_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=bad_resp), patch("time.sleep"):
            result, tokens = client._complete("system", "user")
        assert result is None
        assert tokens == 0

    def test_request_exception_retries(self):
        import requests as req

        client = make_client()

        with patch("requests.post", side_effect=req.exceptions.Timeout("timeout")):
            with patch("time.sleep"):
                result, tokens = client._complete("system", "user")
        assert result is None
        assert tokens == 0


class TestCustomSystemPrompt:
    def test_default_prompt(self):
        client = make_client()
        from rathausrot.scraper import CouncilItem

        item = CouncilItem(
            id="x",
            title="T",
            url="http://x",
            item_type="item",
            date="",
            body_text="body",
            source_system="test",
        )
        system, user = client._build_prompt(item)
        assert "TestPartei" in system

    def test_custom_prompt(self):
        client = make_client(
            openrouter={
                "api_key": "k",
                "model": "m",
                "max_tokens": 100,
                "system_prompt": "Custom prompt here",
            }
        )
        from rathausrot.scraper import CouncilItem

        item = CouncilItem(
            id="x",
            title="T",
            url="http://x",
            item_type="item",
            date="",
            body_text="body",
            source_system="test",
        )
        system, user = client._build_prompt(item)
        assert system == "Custom prompt here"
