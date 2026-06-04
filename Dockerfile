FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 whisperx \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --create-home \
        --home-dir /home/whisperx \
        --shell /usr/sbin/nologin \
        whisperx

COPY pyproject.toml uv.lock README.md /app/
COPY docker/entrypoint.sh /usr/local/bin/whisperx-daemon-entrypoint

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

RUN uv sync --frozen --extra gpu --no-dev --all-packages --no-install-workspace \
    && chmod 0755 /usr/local/bin/whisperx-daemon-entrypoint

COPY src /app/src
COPY whisperx_daemon /app/whisperx_daemon

RUN uv sync --frozen --extra gpu --no-dev --all-packages --no-editable \
    && chmod 0755 /usr/local/bin/whisperx-daemon-entrypoint

RUN mkdir -p /app/runtime \
    && chmod 0777 /app/runtime \
    && chown -R whisperx:whisperx /app /home/whisperx

VOLUME ["/app/runtime"]

USER whisperx

ENTRYPOINT ["/usr/local/bin/whisperx-daemon-entrypoint"]
CMD ["--runtime-dir", "/app/runtime", "--once", "--model", "small", "--device", "cuda", "--compute-type", "float16"]
