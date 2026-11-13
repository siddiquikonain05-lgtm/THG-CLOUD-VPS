FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Common Linux tooling for the terminal (tini reaps orphaned jobs, util-linux provides setpriv)
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash curl wget git nano vim-tiny less zip unzip tar gzip bzip2 xz-utils \
        procps htop psmisc tini util-linux ca-certificates openssh-client \
        build-essential libffi-dev libssl-dev iputils-ping dnsutils net-tools jq sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /bin/bash thg

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY frontend ./frontend
COPY scripts ./scripts
RUN chmod +x scripts/*.sh scripts/thgjob && ln -s /app/scripts/thgjob /usr/local/bin/thgjob

ENV DATA_DIR=/data \
    PORT=8000 \
    THG_APP_ROOT=/app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["/app/scripts/healthcheck.sh"]

ENTRYPOINT ["tini", "--"]
CMD ["/app/scripts/startup.sh"]
