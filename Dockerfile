FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime


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

COPY pyproject.toml README.md /app/
COPY packages/transcript-postprocess /app/packages/transcript-postprocess
COPY src /app/src
COPY whisperx_daemon /app/whisperx_daemon

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache
ENV XDG_CONFIG_HOME=/tmp/.config
ENV HF_HOME=/tmp/.cache/huggingface
ENV TRANSFORMERS_CACHE=/tmp/.cache/huggingface/transformers
ENV MPLCONFIGDIR=/tmp/.config/matplotlib

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir "torchcodec>=0.7,<0.8" \
    && pip install --no-cache-dir sentencepiece \
    && pip install --no-cache-dir whisperx \
    && pip install --no-cache-dir "/app/packages/transcript-postprocess[ner]" \
    && pip install --no-cache-dir .

RUN mkdir -p \
    /tmp/.cache/huggingface/transformers \
    /tmp/.config/matplotlib \
    /app/runtime/input \
    /app/runtime/processing \
    /app/runtime/archive/succeeded \
    /app/runtime/archive/failed \
    /app/runtime/output \
    /app/runtime/failed \
    /app/runtime/logs \
    && chown -R whisperx:whisperx /app /home/whisperx /tmp/.cache /tmp/.config

VOLUME ["/app/runtime"]

USER whisperx

ENTRYPOINT ["python", "-m", "whisperx_daemon"]
CMD ["--runtime-dir", "/app/runtime", "--once", "--model", "small", "--device", "cuda", "--compute-type", "float16"]
