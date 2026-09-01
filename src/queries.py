"""Where search queries come from.

Two query sources are available:

* `llm` (default) asks the provider configured by LLM_PROVIDER. Native Ollama,
  OpenAI-compatible Chat Completions, and Anthropic Messages APIs are supported.
* `trends` uses public feeds and needs no account, model or API key.

    QUERY_SOURCE=trends python src/main.py

The LLM's whole job in this project is producing short strings to type into
Bing, and Bing's own autosuggest answers that question directly.
"""

import logging
import os

import query_sources

# llm_utils is imported inside the llm branch rather than here. That keeps the
# trends path independent of whichever model provider is configured and avoids
# initializing an LLM client during a trends-only run.

logger = logging.getLogger(__name__)

LLM = "llm"
TRENDS = "trends"

DEFAULT_SOURCE = LLM

ENV_VAR = "QUERY_SOURCE"


def selected_source() -> str:
	"""Read on each call so a test can change it without reimporting."""
	choice = os.environ.get(ENV_VAR, DEFAULT_SOURCE).strip().lower()

	return choice if choice in (LLM, TRENDS) else DEFAULT_SOURCE


def search_query_for_task(task_description: str) -> str:
	"""A query for one "Search on Bing for X" card."""
	if selected_source() == TRENDS:
		query = query_sources.query_from_task_description(task_description)

		if query:
			return query

		# Every feed was unreachable. The description still contains the topic,
		# so a trimmed version beats skipping the card entirely.
		logger.warning("No query source reachable, using the lowercased task description.")

		return task_description.lower()

	import llm_utils

	return llm_utils.get_search_query_from_task_description(task_description)


def related_queries(count: int):
	"""`count` queries for the daily search quota."""
	if selected_source() == TRENDS:
		queries = query_sources.related_queries(count)

		if queries:
			return queries

		logger.warning("No query source reachable, falling back to the wordlist.")

		# nouns.txt is already in the repo for exactly this kind of seed.
		return query_sources.wordlist_queries(count)

	import llm_utils

	return llm_utils.get_related_search_queries(llm_utils.get_random_noun(), num_queries=count)
