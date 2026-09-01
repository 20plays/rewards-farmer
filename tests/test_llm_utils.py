import os
import unittest
from unittest import mock

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import llm_utils


LLM_ENV_VARS = (
	llm_utils.PROVIDER_ENV,
	llm_utils.MODEL_ENV,
	llm_utils.BASE_URL_ENV,
	llm_utils.API_KEY_ENV,
	llm_utils.TIMEOUT_ENV,
	llm_utils.EXTRA_HEADERS_ENV,
	llm_utils.MAX_TOKENS_ENV,
	llm_utils.ANTHROPIC_VERSION_ENV,
	"OLLAMA_HOST",
)


class FakeResponse:
	def __init__(self, payload=None, status_code=200, text=""):
		self._payload = payload
		self.status_code = status_code
		self.text = text

	def json(self):
		if isinstance(self._payload, Exception):
			raise self._payload

		return self._payload


class EnvironmentTestCase(unittest.TestCase):
	def setUp(self):
		self.saved = {name: os.environ.get(name) for name in LLM_ENV_VARS}

		for name in LLM_ENV_VARS:
			os.environ.pop(name, None)

	def tearDown(self):
		for name in LLM_ENV_VARS:
			os.environ.pop(name, None)

		for name, value in self.saved.items():
			if value is not None:
				os.environ[name] = value


class TestProviderSelection(EnvironmentTestCase):
	def test_ollama_remains_the_default(self):
		self.assertEqual(llm_utils.selected_provider(), llm_utils.OLLAMA)

	def test_openai_compatible_aliases_resolve_to_openai(self):
		for value in ("openai", "openai-compatible", "openai_compatible"):
			os.environ[llm_utils.PROVIDER_ENV] = value
			self.assertEqual(llm_utils.selected_provider(), llm_utils.OPENAI)

	def test_anthropic_aliases_resolve_to_anthropic(self):
		for value in ("anthropic", "claude"):
			os.environ[llm_utils.PROVIDER_ENV] = value
			self.assertEqual(llm_utils.selected_provider(), llm_utils.ANTHROPIC)

	def test_unknown_provider_fails_with_configuration_error(self):
		os.environ[llm_utils.PROVIDER_ENV] = "mystery"

		with self.assertRaisesRegex(ValueError, "LLM_PROVIDER"):
			llm_utils.selected_provider()


class TestOpenAICompatible(EnvironmentTestCase):
	def setUp(self):
		super().setUp()
		os.environ[llm_utils.PROVIDER_ENV] = "openai"
		os.environ[llm_utils.MODEL_ENV] = "test-model"

	def test_posts_openai_chat_completions_shape(self):
		os.environ[llm_utils.BASE_URL_ENV] = "https://provider.example/v1"
		os.environ[llm_utils.API_KEY_ENV] = "secret-token"
		os.environ[llm_utils.EXTRA_HEADERS_ENV] = '{"X-Title":"rewards-farmer"}'

		response = FakeResponse({
			"choices": [{"message": {"content": "short search query"}}]
		})

		with mock.patch.object(llm_utils.requests, "post", return_value=response) as post:
			result = llm_utils.get_llm_response([{"role": "user", "content": "hello"}])

		self.assertEqual(result, "short search query")

		args, kwargs = post.call_args
		self.assertEqual(args[0], "https://provider.example/v1/chat/completions")
		self.assertEqual(kwargs["json"]["model"], "test-model")
		self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "hello"}])
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
		self.assertEqual(kwargs["headers"]["X-Title"], "rewards-farmer")
		self.assertEqual(kwargs["timeout"], llm_utils.DEFAULT_TIMEOUT)

	def test_full_chat_completions_url_is_not_duplicated(self):
		os.environ[llm_utils.BASE_URL_ENV] = "http://127.0.0.1:1234/v1/chat/completions"

		response = FakeResponse({
			"choices": [{"message": {"content": "local answer"}}]
		})

		with mock.patch.object(llm_utils.requests, "post", return_value=response) as post:
			self.assertEqual(llm_utils.get_llm_response([]), "local answer")

		self.assertEqual(post.call_args.args[0], "http://127.0.0.1:1234/v1/chat/completions")
		self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

	def test_content_parts_are_accepted(self):
		response = FakeResponse({
			"choices": [{
				"message": {
					"content": [
						{"type": "text", "text": "first "},
						{"type": "text", "text": "second"},
					]
				}
			}]
		})

		with mock.patch.object(llm_utils.requests, "post", return_value=response):
			self.assertEqual(llm_utils.get_llm_response([]), "first second")

	def test_http_error_is_bounded_and_does_not_echo_headers(self):
		os.environ[llm_utils.API_KEY_ENV] = "do-not-log-me"
		response = FakeResponse(status_code=401, text="unauthorized")

		with mock.patch.object(llm_utils.requests, "post", return_value=response):
			with self.assertRaises(RuntimeError) as raised:
				llm_utils.get_llm_response([])

		message = str(raised.exception)
		self.assertIn("HTTP 401", message)
		self.assertNotIn("do-not-log-me", message)

	def test_model_is_required_for_openai_compatible_mode(self):
		os.environ.pop(llm_utils.MODEL_ENV, None)

		with self.assertRaisesRegex(ValueError, "LLM_MODEL"):
			llm_utils.get_openai_compatible_response([])


class TestAnthropicMessages(EnvironmentTestCase):
	def setUp(self):
		super().setUp()
		os.environ[llm_utils.PROVIDER_ENV] = "anthropic"
		os.environ[llm_utils.MODEL_ENV] = "claude-test"
		os.environ[llm_utils.API_KEY_ENV] = "anthropic-secret"

	def test_posts_messages_shape_and_extracts_text_blocks(self):
		response = FakeResponse({
			"content": [
				{"type": "text", "text": "short "},
				{"type": "text", "text": "query"},
			]
		})
		messages = [
			{"role": "system", "content": "Be concise."},
			{"role": "user", "content": "Give a query."},
			{"role": "assistant", "content": "previous"},
			{"role": "user", "content": "next"},
		]

		with mock.patch.object(llm_utils.requests, "post", return_value=response) as post:
			result = llm_utils.get_llm_response(messages)

		self.assertEqual(result, "short query")
		args, kwargs = post.call_args
		self.assertEqual(args[0], "https://api.anthropic.com/v1/messages")
		self.assertEqual(kwargs["headers"]["x-api-key"], "anthropic-secret")
		self.assertEqual(
			kwargs["headers"]["anthropic-version"],
			llm_utils.DEFAULT_ANTHROPIC_VERSION
		)
		self.assertEqual(kwargs["json"]["model"], "claude-test")
		self.assertEqual(
			kwargs["json"]["max_tokens"],
			llm_utils.DEFAULT_ANTHROPIC_MAX_TOKENS
		)
		self.assertEqual(kwargs["json"]["system"], "Be concise.")
		self.assertEqual(
			kwargs["json"]["messages"],
			[
				{"role": "user", "content": "Give a query."},
				{"role": "assistant", "content": "previous"},
				{"role": "user", "content": "next"},
			]
		)

	def test_custom_messages_url_and_limits_are_supported(self):
		os.environ[llm_utils.BASE_URL_ENV] = "https://claude-gateway.example/v1/messages"
		os.environ[llm_utils.MAX_TOKENS_ENV] = "64"
		os.environ[llm_utils.ANTHROPIC_VERSION_ENV] = "custom-version"

		response = FakeResponse({"content": [{"type": "text", "text": "ok"}]})

		with mock.patch.object(llm_utils.requests, "post", return_value=response) as post:
			self.assertEqual(
				llm_utils.get_anthropic_response([{"role": "user", "content": "hello"}]),
				"ok"
			)

		self.assertEqual(post.call_args.args[0], "https://claude-gateway.example/v1/messages")
		self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 64)
		self.assertEqual(post.call_args.kwargs["headers"]["anthropic-version"], "custom-version")

	def test_model_is_required_for_anthropic_mode(self):
		os.environ.pop(llm_utils.MODEL_ENV, None)

		with self.assertRaisesRegex(ValueError, "LLM_MODEL"):
			llm_utils.get_anthropic_response([{"role": "user", "content": "hello"}])

	def test_unknown_role_is_rejected_before_request(self):
		with self.assertRaisesRegex(ValueError, "does not support role"):
			llm_utils.get_anthropic_response([{"role": "tool", "content": "hello"}])

	def test_max_tokens_must_be_positive_integer(self):
		os.environ[llm_utils.MAX_TOKENS_ENV] = "nope"

		with self.assertRaisesRegex(ValueError, "LLM_MAX_TOKENS"):
			llm_utils.get_anthropic_response([{"role": "user", "content": "hello"}])


class TestRetries(EnvironmentTestCase):
	def test_empty_responses_stop_after_five_attempts(self):
		with mock.patch.object(llm_utils, "get_llm_response", return_value="") as call:
			with self.assertRaisesRegex(RuntimeError, "after 5 attempts"):
				llm_utils.get_nonempty_llm_response([])

		self.assertEqual(call.call_count, llm_utils.MAX_EMPTY_RETRIES)


if __name__ == "__main__":
	unittest.main()
