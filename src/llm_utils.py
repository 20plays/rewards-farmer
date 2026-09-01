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

PROVIDER_ENV = "LLM_PROVIDER"
MODEL_ENV = "LLM_MODEL"
BASE_URL_ENV = "LLM_BASE_URL"
API_KEY_ENV = "LLM_API_KEY"
TIMEOUT_ENV = "LLM_TIMEOUT"
EXTRA_HEADERS_ENV = "LLM_EXTRA_HEADERS_JSON"

DEFAULT_PROVIDER = OLLAMA
DEFAULT_OLLAMA_MODEL = "gemma4:cloud"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 180.0
MAX_EMPTY_RETRIES = 5

_PROVIDER_ALIASES = {
	"ollama": OLLAMA,
	"openai": OPENAI,
	"openai-compatible": OPENAI,
	"openai_compatible": OPENAI,
}


def selected_provider() -> str:
	raw = os.environ.get(PROVIDER_ENV, DEFAULT_PROVIDER).strip().lower()
	provider = _PROVIDER_ALIASES.get(raw)

	if not provider:
		raise ValueError(
			f"{PROVIDER_ENV}={raw!r} is not supported; use 'ollama' or 'openai'"
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


def _model(provider: str) -> str:
	configured = os.environ.get(MODEL_ENV, "").strip()

	if configured:
		return configured

	if provider == OLLAMA:
		return DEFAULT_OLLAMA_MODEL

	raise ValueError(
		f"{MODEL_ENV} is required when {PROVIDER_ENV}={OPENAI!r}"
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


def _openai_chat_url() -> str:
	base = os.environ.get(BASE_URL_ENV, DEFAULT_OPENAI_BASE_URL).strip()

	if not base:
		base = DEFAULT_OPENAI_BASE_URL

	base = base.rstrip("/")

	if base.endswith("/chat/completions"):
		return base

	return f"{base}/chat/completions"


def _content_from_openai_payload(payload: dict) -> str:
	try:
		content = payload["choices"][0]["message"]["content"]
	except (KeyError, IndexError, TypeError) as exc:
		raise RuntimeError("LLM API response did not contain choices[0].message.content") from exc

	if isinstance(content, str):
		return content

	# A few OpenAI-compatible servers return content parts instead of one
	# string. Accept the common text-part shape rather than rejecting a response
	# that still contains exactly what this project needs.
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

	if response.status_code >= 400:
		# Keep the useful provider error text, but cap it so an HTML error page
		# cannot flood an unattended log. Headers (including the API key) are
		# never included in the exception.
		detail = " ".join((response.text or "").split())[:400]
		suffix = f": {detail}" if detail else ""

		raise RuntimeError(f"LLM API returned HTTP {response.status_code}{suffix}")

	try:
		payload = response.json()
	except ValueError as exc:
		raise RuntimeError("LLM API returned a non-JSON response") from exc

	return _content_from_openai_payload(payload)


def get_ollama_response(
	messages: list[dict[str, str]],
	model: str | None = None
) -> str:
	# Import lazily so an OpenAI-compatible or trends-only setup does not need
	# the Ollama client just to import the query code.
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
