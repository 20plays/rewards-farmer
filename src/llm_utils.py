from typing import Generator
import json
import logging
import os
import random

import requests

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT_FOR_SEARCH_QUEST = (
	"You are a helpful assistant tasked with creating a search query based on a directive. "
	"Output nothing but the search query you create, and do not include any additional commentary or explanation. "
	"Do not include any labels or quotes. "
	"The search query must be the only output, and do not format the query as an imperative to 'search for' something. "
	"Imagine that your output will be fed directly into a search engine as you provide it. "
	"For example, if the directive is 'Search on Bing for the latest news about space exploration', you might output 'latest news space exploration'. "
	"Outputting 'search on Bing for the latest news about space exploration' or 'search bing.com/news for space exploration' would be incorrect, "
	"as those answers include instructions to perform a search rather than just the search query itself. "
	"Additionally, be specific, e.g. if a prompt asks you to search for vacation flights, include "
	"a specific destination rather than just searching 'vacation flights'. The current year is 2026. "
	"Make your query concise, ideally 6 words or less, and do not include any punctuation. "
)

DEFAULT_USER_PROMPT_FOR_SEARCH_QUEST_WITHOUT_DESC = """Base your search query on the following task description: """

DEFAULT_SYSTEM_PROMPT_FOR_SEARCH_POINTS = (
	"The user is interested in learning more about topics related to a word that will be given to you. "
	"Your task is to come up with subsequent search queries that relate to each other, each one branching out "
	"from the previous one so that the user can explore a topic in depth. Your first search query should be "
	"based on the word that the user gives you, and each subsequent search query should be at least remotely based on the previous ones. "
	"Output only the single search query you come up with and do not include any additional commentary or explanation. Do not include any labels or quotes. "
	"The search queries should ideally be short (6 words max) and do not need to be fully fledged questions, but they should be unique. The current year is 2026."
)

DEFAULT_USER_PROMPT_FOR_SEARCH_POINTS_WITHOUT_DESC = """Generate the first search query based on the following word: """

USER_PROMPT_FOR_SEARCH_QUERY_CONTINUATION = """Generate the next search query."""

OLLAMA = "ollama"
OPENAI = "openai"
ANTHROPIC = "anthropic"

PROVIDER_ENV = "LLM_PROVIDER"
MODEL_ENV = "LLM_MODEL"
BASE_URL_ENV = "LLM_BASE_URL"
API_KEY_ENV = "LLM_API_KEY"
TIMEOUT_ENV = "LLM_TIMEOUT"
EXTRA_HEADERS_ENV = "LLM_EXTRA_HEADERS_JSON"
MAX_TOKENS_ENV = "LLM_MAX_TOKENS"
ANTHROPIC_VERSION_ENV = "LLM_ANTHROPIC_VERSION"

DEFAULT_PROVIDER = OLLAMA
DEFAULT_OLLAMA_MODEL = "gemma4:cloud"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = 180.0
MAX_EMPTY_RETRIES = 5

_PROVIDER_ALIASES = {
	"ollama": OLLAMA,
	"openai": OPENAI,
	"openai-compatible": OPENAI,
	"openai_compatible": OPENAI,
	"anthropic": ANTHROPIC,
	"claude": ANTHROPIC,
}


def selected_provider() -> str:
	raw = os.environ.get(PROVIDER_ENV, DEFAULT_PROVIDER).strip().lower()
	provider = _PROVIDER_ALIASES.get(raw)

	if not provider:
		raise ValueError(
			f"{PROVIDER_ENV}={raw!r} is not supported; use 'ollama', 'openai', or 'anthropic'"
		)

	return provider


def _timeout() -> float:
	raw = os.environ.get(TIMEOUT_ENV, "").strip()

	if not raw:
		return DEFAULT_TIMEOUT

	try:
		value = float(raw)
	except ValueError as exc:
		raise ValueError(f"{TIMEOUT_ENV} must be a number of seconds") from exc

	if value <= 0:
		raise ValueError(f"{TIMEOUT_ENV} must be greater than zero")

	return value


def _anthropic_max_tokens() -> int:
	raw = os.environ.get(MAX_TOKENS_ENV, "").strip()

	if not raw:
		return DEFAULT_ANTHROPIC_MAX_TOKENS

	try:
		value = int(raw)
	except ValueError as exc:
		raise ValueError(f"{MAX_TOKENS_ENV} must be a positive integer") from exc

	if value <= 0:
		raise ValueError(f"{MAX_TOKENS_ENV} must be a positive integer")

	return value


def _model(provider: str) -> str:
	configured = os.environ.get(MODEL_ENV, "").strip()

	if configured:
		return configured

	if provider == OLLAMA:
		return DEFAULT_OLLAMA_MODEL

	raise ValueError(
		f"{MODEL_ENV} is required when {PROVIDER_ENV}={provider!r}"
	)


def _extra_headers() -> dict[str, str]:
	raw = os.environ.get(EXTRA_HEADERS_ENV, "").strip()

	if not raw:
		return {}

	try:
		payload = json.loads(raw)
	except json.JSONDecodeError as exc:
		raise ValueError(f"{EXTRA_HEADERS_ENV} must contain a JSON object") from exc

	if not isinstance(payload, dict):
		raise ValueError(f"{EXTRA_HEADERS_ENV} must contain a JSON object")

	return {str(key): str(value) for key, value in payload.items()}


def _endpoint(base_default: str, suffix: str) -> str:
	base = os.environ.get(BASE_URL_ENV, base_default).strip() or base_default
	base = base.rstrip("/")

	if base.endswith(suffix):
		return base

	return f"{base}{suffix}"


def _openai_chat_url() -> str:
	return _endpoint(DEFAULT_OPENAI_BASE_URL, "/chat/completions")


def _anthropic_messages_url() -> str:
	return _endpoint(DEFAULT_ANTHROPIC_BASE_URL, "/messages")


def _raise_for_llm_http_error(response) -> None:
	if response.status_code < 400:
		return

	# Keep useful provider text but cap it so an HTML error page cannot flood
	# unattended logs. Request headers, including API keys, are never included.
	detail = " ".join((response.text or "").split())[:400]
	suffix = f": {detail}" if detail else ""

	raise RuntimeError(f"LLM API returned HTTP {response.status_code}{suffix}")


def _json_response(response) -> dict:
	try:
		payload = response.json()
	except ValueError as exc:
		raise RuntimeError("LLM API returned a non-JSON response") from exc

	if not isinstance(payload, dict):
		raise RuntimeError("LLM API returned a JSON response with an unexpected shape")

	return payload


def _content_from_openai_payload(payload: dict) -> str:
	try:
		content = payload["choices"][0]["message"]["content"]
	except (KeyError, IndexError, TypeError) as exc:
		raise RuntimeError("LLM API response did not contain choices[0].message.content") from exc

	if isinstance(content, str):
		return content

	# A few OpenAI-compatible servers return content parts instead of one
	# string. Accept the common text-part shape.
	if isinstance(content, list):
		parts = []

		for part in content:
			if isinstance(part, str):
				parts.append(part)
			elif isinstance(part, dict) and isinstance(part.get("text"), str):
				parts.append(part["text"])

		if parts:
			return "".join(parts)

	raise RuntimeError("LLM API returned an unsupported message content shape")


def get_openai_compatible_response(
	messages: list[dict[str, str]],
	model: str | None = None
) -> str:
	headers = {"Content-Type": "application/json"}
	api_key = os.environ.get(API_KEY_ENV, "").strip()

	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"

	headers.update(_extra_headers())

	try:
		response = requests.post(
			_openai_chat_url(),
			headers=headers,
			json={
				"model": model or _model(OPENAI),
				"messages": messages,
				"stream": False,
			},
			timeout=_timeout(),
		)
	except requests.RequestException as exc:
		raise RuntimeError(f"LLM API request failed: {exc}") from exc

	_raise_for_llm_http_error(response)

	return _content_from_openai_payload(_json_response(response))


def _anthropic_request_parts(
	messages: list[dict[str, str]]
) -> tuple[str | None, list[dict[str, str]]]:
	system_parts = []
	conversation = []

	for message in messages:
		role = message.get("role")
		content = message.get("content", "")

		if role == "system":
			system_parts.append(content)
		elif role in ("user", "assistant"):
			conversation.append({"role": role, "content": content})
		else:
			raise ValueError(f"Anthropic Messages does not support role {role!r}")

	system = "\n\n".join(part for part in system_parts if part).strip()

	return (system or None), conversation


def _content_from_anthropic_payload(payload: dict) -> str:
	content = payload.get("content")

	if not isinstance(content, list):
		raise RuntimeError("Anthropic API response did not contain a content block list")

	parts = [
		block["text"]
		for block in content
		if isinstance(block, dict)
		and block.get("type") == "text"
		and isinstance(block.get("text"), str)
	]

	if not parts:
		raise RuntimeError("Anthropic API response did not contain a text content block")

	return "".join(parts)


def get_anthropic_response(
	messages: list[dict[str, str]],
	model: str | None = None
) -> str:
	system, conversation = _anthropic_request_parts(messages)
	headers = {
		"Content-Type": "application/json",
		"anthropic-version": (
			os.environ.get(ANTHROPIC_VERSION_ENV, "").strip()
			or DEFAULT_ANTHROPIC_VERSION
		),
	}
	api_key = os.environ.get(API_KEY_ENV, "").strip()

	if api_key:
		headers["x-api-key"] = api_key

	headers.update(_extra_headers())

	body = {
		"model": model or _model(ANTHROPIC),
		"max_tokens": _anthropic_max_tokens(),
		"messages": conversation,
	}

	if system:
		body["system"] = system

	try:
		response = requests.post(
			_anthropic_messages_url(),
			headers=headers,
			json=body,
			timeout=_timeout(),
		)
	except requests.RequestException as exc:
		raise RuntimeError(f"LLM API request failed: {exc}") from exc

	_raise_for_llm_http_error(response)

	return _content_from_anthropic_payload(_json_response(response))


def get_ollama_response(
	messages: list[dict[str, str]],
	model: str | None = None
) -> str:
	# Import lazily so an HTTP-provider or trends-only setup does not need the
	# Ollama client just to import the query code.
	import ollama

	client_kwargs = {"timeout": _timeout()}
	host = (
		os.environ.get(BASE_URL_ENV, "").strip()
		or os.environ.get("OLLAMA_HOST", "").strip()
	)

	if host:
		client_kwargs["host"] = host

	client = ollama.Client(**client_kwargs)
	response = client.chat(
		model=model or _model(OLLAMA),
		messages=messages
	)

	return response.message.content


def get_llm_response(messages: list[dict[str, str]]) -> str:
	provider = selected_provider()

	if provider == OPENAI:
		return get_openai_compatible_response(messages)

	if provider == ANTHROPIC:
		return get_anthropic_response(messages)

	return get_ollama_response(messages)


def get_nonempty_llm_response(messages: list[dict[str, str]]) -> str:
	"""Retry a bounded number of times instead of spinning forever on empties."""
	for attempt in range(MAX_EMPTY_RETRIES):
		response = get_llm_response(messages)

		if response and response.strip():
			return response

		logger.warning("Empty LLM response, retry %s/%s", attempt + 1, MAX_EMPTY_RETRIES)

	raise RuntimeError(f"LLM returned nothing usable after {MAX_EMPTY_RETRIES} attempts")


def get_nonempty_ollama_response(messages: list[dict[str, str]]) -> str:
	"""Backward-compatible name retained for callers outside this repository."""
	return get_nonempty_llm_response(messages)


def get_search_query_from_task_description(task_description: str) -> str:
	# compat
	if "lyrics of your favorite song" in task_description.lower():
		return "sweet caroline lyrics"

	messages = [
		{
			"role": "system",
			"content": DEFAULT_SYSTEM_PROMPT_FOR_SEARCH_QUEST
		},
		{
			"role": "user",
			"content": DEFAULT_USER_PROMPT_FOR_SEARCH_QUEST_WITHOUT_DESC + task_description
		}
	]

	response = get_nonempty_llm_response(messages)

	return response.lower()


def get_related_search_queries(seed_word: str, num_queries: int = 20) -> Generator[str, None, None]:
	messages = [
		{
			"role": "system",
			"content": DEFAULT_SYSTEM_PROMPT_FOR_SEARCH_POINTS
		},
		{
			"role": "user",
			"content": DEFAULT_USER_PROMPT_FOR_SEARCH_POINTS_WITHOUT_DESC + seed_word
		}
	]

	for _ in range(num_queries):
		response = get_nonempty_llm_response(messages)

		yield response.lower()

		messages.append({
			"role": "assistant",
			"content": response
		})

		messages.append({
			"role": "user",
			"content": USER_PROMPT_FOR_SEARCH_QUERY_CONTINUATION
		})


NOUNS = [
	noun.strip().lower() for noun in open("nouns.txt", "r", encoding="utf-8").read().splitlines()
	if len(noun.strip()) >= 3
]


def get_random_noun() -> str:
	return random.choice(NOUNS)
