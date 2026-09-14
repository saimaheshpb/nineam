import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from app.services import llm


def completion(content, *, finish_reason="stop"):
    response = Mock()
    response.model = "selected/model"
    response.choices = [
        Mock(finish_reason=finish_reason, message=Mock(content=content))
    ]
    response.model_dump.return_value = {
        "id": "generation-1",
        "choices": [{"message": {"provider_metadata": {
            "gateway": {"routing": {"finalProvider": "example-provider"}}
        }}}],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 30,
            "completion_tokens_details": {"reasoning_tokens": 4},
            "cost": 0.001,
        },
    }
    return response


class GatewayStructuredOutputTests(unittest.TestCase):
    @patch("app.services.llm._gateway_client")
    def test_every_role_schema_is_requested_and_locally_validated(self, client):
        cases = [
            (llm.ArticleData, {
                "headline": "Example", "summary": "Summary", "entities": [],
                "category": "ai", "importance_score": 5,
                "key_facts": [{"claim": "Fact", "supporting_excerpt": "Fact"}],
            }),
            (llm.GeneratedArticle, {"title": "Title", "body": "Body"}),
            (llm.ClaimExtractionResult, {"claims": [{
                "source_sentence_index": 0,
                "claim_text": "Claim",
                "is_factual": True,
            }]}),
            (llm.ClaimJudgeResult, {"verdicts": [{
                "claim_index": 1,
                "verdict": "supported",
                "confidence": 1.0,
                "severity": "none",
                "rationale": "Direct support",
            }]}),
        ]
        for schema_type, payload in cases:
            with self.subTest(schema=schema_type.__name__):
                client.return_value.chat.completions.create.return_value = (
                    completion(json.dumps(payload))
                )
                with redirect_stdout(io.StringIO()) as output:
                    result = llm._request_structured(
                        "test_role", "selected/model", schema_type,
                        "Prompt", "Input",
                    )
                self.assertEqual(result, payload)
                request = client.return_value.chat.completions.create.call_args.kwargs
                self.assertEqual(request["model"], "selected/model")
                self.assertEqual(request["messages"][1]["content"], "Input")
                self.assertTrue(request["response_format"]["json_schema"]["strict"])
                self.assertFalse(request["response_format"]["json_schema"]["schema"]["additionalProperties"])
                self.assertNotIn("max_completion_tokens", request)
                self.assertNotIn("timeout", request)
                self.assertIn('"provider": "example-provider"', output.getvalue())

    def test_nested_pydantic_schemas_are_strict(self):
        article_schema = llm._strict_json_schema(llm.GeneratedArticle)
        self.assertEqual(set(article_schema["properties"]), {"title", "body"})
        self.assertEqual(set(article_schema["required"]), {"title", "body"})
        for schema_type, field in (
            (llm.ArticleData, "key_facts"),
            (llm.ClaimExtractionResult, "claims"),
            (llm.ClaimJudgeResult, "verdicts"),
        ):
            with self.subTest(schema=schema_type.__name__):
                item_schema = llm._strict_json_schema(schema_type)["properties"][field]["items"]
                self.assertFalse(item_schema["additionalProperties"])
                self.assertEqual(
                    set(item_schema["required"]),
                    set(item_schema["properties"]),
                )

    @patch("app.services.llm._gateway_client")
    def test_malformed_or_missing_output_fails_without_retry(self, client):
        create = client.return_value.chat.completions.create
        for response in (
            completion("not-json"),
            completion(""),
            completion(json.dumps({"verdicts": [{"verdict": "unknown"}]})),
            completion(json.dumps({"verdicts": []}), finish_reason="length"),
        ):
            with self.subTest(content=response.choices[0].message.content):
                create.reset_mock()
                create.return_value = response
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(RuntimeError):
                        llm._request_structured(
                            "judge", "selected/model", llm.ClaimJudgeResult,
                            "Prompt", "Input",
                        )
                create.assert_called_once()

    @patch("app.services.llm._gateway_client")
    def test_provider_error_is_surfaced_without_credential(self, client):
        secret = "vck_test_secret_never_log_this_12345"
        client.return_value.chat.completions.create.side_effect = RuntimeError(
            f"provider failed with {secret}"
        )
        with patch.dict(os.environ, {"AI_GATEWAY_API_KEY": secret}):
            with redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(RuntimeError, "evidence failed with selected/model"):
                    llm._request_structured(
                        "evidence", "selected/model", llm.ArticleData,
                        "Prompt", "Input",
                    )
        self.assertNotIn(secret, output.getvalue())
        client.return_value.chat.completions.create.assert_called_once()

    def test_missing_key_is_reported_at_call_time(self):
        with patch.dict(os.environ, {"AI_GATEWAY_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "AI_GATEWAY_API_KEY is missing"):
                llm._gateway_client()


if __name__ == "__main__":
    unittest.main()
