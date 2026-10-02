import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODEL_VARIABLES = (
    "EVIDENCE_EXTRACTION_MODEL",
    "ARTICLE_GENERATION_MODEL",
    "CLAIM_EXTRACTION_MODEL",
    "CLAIM_JUDGE_MODEL",
)

CONFIG_FILES = (
    ".github/workflows/daily.yml",
    ".github/workflows/evaluate.yml",
    ".env.example",
)


def code_defaults() -> dict[str, str]:
    """Read defaults from llm.py source so a local .env cannot mask drift."""
    source = (ROOT / "app/services/llm.py").read_text()
    defaults = {}
    for name in MODEL_VARIABLES:
        match = re.search(
            rf'os\.getenv\(\s*"{name}"\s*,\s*"([^"]+)"\s*\)', source
        )
        if match is None:
            raise AssertionError(f"No default found for {name} in llm.py")
        defaults[name] = match.group(1)
    return defaults


def configured_models(path: str) -> dict[str, str]:
    text = (ROOT / path).read_text()
    models = {}
    for name in MODEL_VARIABLES:
        match = re.search(rf"^\s*{name}\s*[:=]\s*(\S+)\s*$", text, re.MULTILINE)
        if match is not None:
            models[name] = match.group(1)
    return models


class ModelConfigurationDriftTests(unittest.TestCase):
    def test_workflows_and_env_example_match_code_defaults(self):
        expected = code_defaults()
        for path in CONFIG_FILES:
            with self.subTest(path=path):
                configured = configured_models(path)
                self.assertEqual(
                    set(configured), set(MODEL_VARIABLES),
                    f"{path} should set all four model roles",
                )
                self.assertEqual(configured, expected)


if __name__ == "__main__":
    unittest.main()
