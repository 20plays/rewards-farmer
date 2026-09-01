# 20plays/rewards-farmer

Fork of `User0332/rewards-farmer`, with additional reliability and provider support.

Automation for MS Rewards based on [https://youtu.be/4qdPcMNaioA](https://youtu.be/4qdPcMNaioA).

# Running Instructions

IMPORTANT: Use at your own risk. Microsoft may take action against your account for using automated scripts to gain rewards points. The YouTube video contains more details about the techniques implemented to avoid detection of this script.

Clone the repository.

```sh
git clone https://github.com/20plays/rewards-farmer
```

A sample `nouns.txt` file is included in the project root and can be modified by the user to contain seed words for the LLM to complete 20 searches. The wordlist should be separated by newline.

```sh
cd rewards-farmer
# Edit the included nouns.txt file to add or replace words as needed
```

# Where search queries come from

The bot needs short strings to type into Bing. `QUERY_SOURCE` chooses how those strings are produced:

| `QUERY_SOURCE` | Needs | Notes |
| --- | --- | --- |
| `llm` (default) | a configured LLM provider | Ollama, OpenAI-compatible Chat Completions, or Anthropic Messages |
| `trends` | nothing | Google Trends, Wikipedia and Bing autosuggest |

```sh
QUERY_SOURCE=trends python src/main.py          # bash
$env:QUERY_SOURCE="trends"; python src/main.py  # PowerShell
```

`trends` needs no account, API key or model. If every feed is unreachable it falls back to `nouns.txt` rather than failing the run.

## LLM providers and APIs

When `QUERY_SOURCE=llm`, `LLM_PROVIDER` selects the transport:

| `LLM_PROVIDER` | Configuration | What it supports |
| --- | --- | --- |
| `ollama` (default) | optional `LLM_MODEL`, `OLLAMA_HOST` or `LLM_BASE_URL` | local Ollama and Ollama cloud |
| `openai` | `LLM_MODEL`, optional `LLM_BASE_URL`, `LLM_API_KEY` | any server implementing the OpenAI `/chat/completions` response shape |
| `anthropic` | `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_BASE_URL` | Anthropic's native Messages API shape |

The OpenAI-compatible path is intentionally provider-neutral. It can point at a hosted API or a local server such as LM Studio, vLLM, llama.cpp server or LocalAI, as long as the endpoint accepts OpenAI-style chat completions.

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai`, or `anthropic` |
| `LLM_MODEL` | `gemma4:cloud` for Ollama | model identifier; required for `openai` and `anthropic` |
| `LLM_BASE_URL` | provider default | API base URL, or the full provider endpoint |
| `LLM_API_KEY` | unset | Bearer key for OpenAI-compatible APIs; `x-api-key` for Anthropic |
| `LLM_TIMEOUT` | `180` | request timeout in seconds |
| `LLM_EXTRA_HEADERS_JSON` | unset | optional JSON object of extra HTTP headers |
| `LLM_MAX_TOKENS` | `1024` | Anthropic response token cap; lower it if your chosen model reliably emits short answers |
| `LLM_ANTHROPIC_VERSION` | `2023-06-01` | Anthropic Messages API version header |
| `OLLAMA_HOST` | Ollama client default | existing Ollama host setting; `LLM_BASE_URL` takes precedence |

Example: native Ollama (the existing behavior):

```sh
QUERY_SOURCE=llm LLM_PROVIDER=ollama LLM_MODEL=gemma4:cloud python src/main.py
```

Example: a hosted OpenAI-compatible API:

```sh
QUERY_SOURCE=llm \
LLM_PROVIDER=openai \
LLM_MODEL="your-model-id" \
LLM_BASE_URL="https://provider.example/v1" \
LLM_API_KEY="your-api-key" \
python src/main.py
```

Example: a local OpenAI-compatible server with no key:

```sh
QUERY_SOURCE=llm \
LLM_PROVIDER=openai \
LLM_MODEL="your-local-model" \
LLM_BASE_URL="http://127.0.0.1:1234/v1" \
python src/main.py
```

Example: Anthropic Messages API:

```sh
QUERY_SOURCE=llm \
LLM_PROVIDER=anthropic \
LLM_MODEL="your-claude-model-id" \
LLM_API_KEY="your-anthropic-api-key" \
python src/main.py
```

For providers that ask for additional headers, pass them without editing the source:

```sh
LLM_EXTRA_HEADERS_JSON='{"HTTP-Referer":"https://example.com","X-Title":"rewards-farmer"}'
```

Do not put real API keys in the repository. Set them in your shell, service manager, CI secret store, or another environment-injection mechanism.

For Docker Compose, you can copy `.env.example` to `.env` and fill in the values. Compose reads `.env` automatically, and the repository ignores it so credentials are not accidentally committed:

```sh
cp .env.example .env
docker compose run --rm rewards-farmer
```

A plain host-side `python src/main.py` run reads normal process environment variables; it does not parse `.env` itself.

You must also provide an image for the script to upload to complete the visual search task. A helper script is included at `src/random_image_for_visual_search.py` that will download an image from Wikipedia named `visual_search.jpg` into the project root for you. You may also provide an image of your own, just ensure that the absolute path of the image is placed in the `VISUAL_SEARCH_IMAGE_PATH` constant at the top of `rewards_tasks.py`.

Activate the virtual environment & install dependencies (you may have to use `python -m poetry` instead of `poetry`).
You must have Python 3.12+ and Poetry installed.

If `iex (poetry env activate)` fails with *"Cannot bind argument to parameter 'Command' because it is null"*, `poetry install` did not create an environment. Run `python --version` first: an older Python leaves poetry with nothing to activate, and the message explaining that goes to stderr rather than into `iex`.

Windows (PowerShell)
```sh
poetry install
iex (poetry env activate)
```

*nix (Bash)
```sh
poetry install
eval $(poetry env activate)
```

You must also have a [webdriver for Microsoft Edge](https://learn.microsoft.com/en-us/microsoft-edge/webdriver/?tabs=c-sharp) installed. If you already have the Edge Browser installed, you probably have this component as well.

The profile directory in `src/constants.py` is set to `Default`. If this signs you in to a global profile that you do not want to use for automation, then you can create a new profile from within the webdriver instance manually and then change the `PROFILE_NAME` constant to `Profile 1` (or the equivalent number).

Run main.py (`python src/main.py`, it must be run from the root directory so the relative paths work out), wait for the page to launch, and then CTRL-C to quit the application immediately. Sign in to the created profile with your Microsoft account on both Bing and `rewards.bing.com`.

EU Users: you may have to accept a consent banner once on `rewards.bing.com` and on the Bing search page, `bing.com`. Once you consent, your choice will be saved for future runs using the same profile, so you will not need to interact with the banner during automated runs.

Close all webdriver browser instances. Run `main.py` again; the automation should start working.

# Running more than one account

Rewards is per Microsoft account and the browser profile holds the sign-in, so an account here is a profile directory. `REWARDS_ACCOUNTS` takes a comma separated list, and each name gets its own directory under `data-dir`:

```sh
REWARDS_ACCOUNTS=personal,spare python src/main.py
```

Each is signed in once by hand, the same way as the single profile, using its own directory:

```
msedge --user-data-dir="<repo>\data-dir\personal" --profile-directory=Default https://rewards.bing.com
```

They run one after another, and an account that fails is reported and skipped rather than ending the run, whether it fails to start or dies partway through. Leave `REWARDS_ACCOUNTS` unset and everything behaves exactly as before, using the single profile in `data-dir`.

# Docker

Docker runs the farmer without installing Edge, a matching driver, or Python on the host.

```sh
docker compose build
docker compose run --rm rewards-farmer
```

The container defaults to `QUERY_SOURCE=trends`, so it needs no model or API key. The compose file also passes through all of the LLM variables documented above.

For an Ollama server running on the host:

```sh
QUERY_SOURCE=llm \
LLM_PROVIDER=ollama \
OLLAMA_HOST=host.docker.internal:11434 \
docker compose run --rm rewards-farmer
```

For an OpenAI-compatible API, set `QUERY_SOURCE=llm`, `LLM_PROVIDER=openai`, `LLM_MODEL`, and the appropriate `LLM_BASE_URL`/`LLM_API_KEY` values before running Compose. For Anthropic, use `LLM_PROVIDER=anthropic`, a Claude model ID, and `LLM_API_KEY`.

## Sign in from inside the container

This is the recommended Docker setup, especially on Windows and macOS hosts:

```sh
docker compose run --rm --service-ports signin
```

Open <http://localhost:6080>, sign in to Microsoft/Rewards in the Edge window shown there, then **close the Edge window on that screen**. The sign-in container exits and the profile remains in `data-dir`.

`--service-ports` is required because `docker compose run` does not publish service ports by default.

The noVNC page is published as `127.0.0.1:6080` only. It is intentionally not exposed to the LAN: while this service is running, that page contains a live Microsoft sign-in browser session. The underlying VNC port is not published at all.

Why this matters: Chromium encrypts cookie values with an OS-derived key. A profile written by normal Edge on Windows uses DPAPI, and macOS uses the login Keychain; the Linux container cannot unwrap those host keys. Signing in with the container's own Edge makes the same environment both write and later read the profile.

Sign-in remains fully manual. The helper does not read, store, or type your credentials.

If you interrupt the sign-in container with Ctrl-C or `docker stop`, run the sign-in flow again before assuming the session was saved. Chromium persists some session state during its own clean browser shutdown, so closing the Edge window is the reliable path.

For multiple accounts, sign in one profile at a time and then run them together:

```sh
REWARDS_ACCOUNTS=personal docker compose run --rm --service-ports signin
REWARDS_ACCOUNTS=spare    docker compose run --rm --service-ports signin

REWARDS_ACCOUNTS=personal,spare docker compose run --rm rewards-farmer
```

You can still sign in using a host browser on platforms where the host and container can read the same Chromium cookie key, but the in-container flow avoids that dependency.

## Visual search in Docker

`visual_search.jpg` is not tracked in the repository. Create it once on the host:

```sh
python src/random_image_for_visual_search.py
```

Compose mounts it read-only into the container. If it is absent, the other tasks can still run; only visual search will fail/skip.

`REWARDS_HEADLESS=1` is set for normal container runs. The dedicated `signin` service is the exception: it launches a headful Edge window on a virtual display and serves that display through noVNC.

# Logging

The script logs to the console. Two optional environment variables change that:

| Variable | Default | Effect |
| --- | --- | --- |
| `REWARDS_FARMER_LOG_LEVEL` | `INFO` | Set to `DEBUG` to also attach the full stack trace to every `[FAIL]` line. |
| `REWARDS_FARMER_LOG_FILE` | unset | Path to also write the log to, useful for unattended runs. |

Windows (PowerShell)
```sh
$env:REWARDS_FARMER_LOG_LEVEL="DEBUG"; $env:REWARDS_FARMER_LOG_FILE="run.log"; python src/main.py
```

*nix (Bash)
```sh
REWARDS_FARMER_LOG_LEVEL=DEBUG REWARDS_FARMER_LOG_FILE=run.log python src/main.py
```

If you are opening an issue about a crash, running with `REWARDS_FARMER_LOG_LEVEL=DEBUG` and attaching the log is the most useful thing you can include.

Please open up a GitHub issue if you run into any difficulties.