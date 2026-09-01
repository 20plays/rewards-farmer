# Runs the bot without installing Edge, a driver or Python on the host.
#
# The runtime image contains the browser automation dependencies plus the small
# noVNC stack used only by src/signin.py. Developer-only recording/visualisation
# packages are still left out of the image.
#
# QUERY_SOURCE defaults to trends here so a container needs no LLM at all.
# Set it to llm to use either Ollama or an OpenAI-compatible API; provider
# settings are passed through by docker-compose.yml.

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Edge, from Microsoft's own repository.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ca-certificates curl gnupg unzip fonts-liberation \
	&& curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
		| gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
	&& echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" \
		> /etc/apt/sources.list.d/microsoft-edge.list \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends microsoft-edge-stable \
	&& rm -rf /var/lib/apt/lists/*

# The driver has to match the browser build, so it is pinned to whatever Edge
# the layer above installed rather than to "latest", which drifts apart from it
# between releases.
RUN EDGE_VERSION="$(microsoft-edge --version | awk '{print $3}')" \
	&& curl -fsSL -o /tmp/edgedriver.zip \
		"https://msedgedriver.microsoft.com/${EDGE_VERSION}/edgedriver_linux64.zip" \
	&& unzip -j /tmp/edgedriver.zip msedgedriver -d /usr/local/bin \
	&& chmod +x /usr/local/bin/msedgedriver \
	&& rm /tmp/edgedriver.zip \
	&& msedgedriver --version

# In-container sign-in needs a headful browser. Xvfb supplies the display,
# x11vnc exposes that display only inside the container, and websockify/noVNC
# serves it to the host browser. docker-compose publishes only 127.0.0.1:6080.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		xvfb x11vnc novnc websockify \
	&& rm -rf /var/lib/apt/lists/* \
	&& ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

WORKDIR /app

RUN pip install --no-cache-dir \
	"selenium>=4.46.0,<5.0.0" \
	"numpy" \
	"requests>=2.32.0" \
	"ollama>=0.6.2,<0.7.0"

COPY src/ ./src/
COPY nouns.txt ./

# Headless because there is no display during a normal farming run, and trends
# because that mode needs no model or API credentials.
ENV REWARDS_HEADLESS=1 \
	QUERY_SOURCE=trends \
	PYTHONUNBUFFERED=1

VOLUME ["/app/data-dir"]

CMD ["python", "src/main.py"]
