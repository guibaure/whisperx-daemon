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
ENV XDG_CACHE_HOME=/tmp/whisperx-cache
ENV XDG_CONFIG_HOME=/tmp/whisperx-config
ENV HF_HOME=/tmp/whisperx-huggingface
ENV TRANSFORMERS_CACHE=/tmp/whisperx-huggingface/transformers
ENV MPLCONFIGDIR=/tmp/whisperx-matplotlib

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir "torchcodec>=0.7,<0.8" \
    && pip install --no-cache-dir sentencepiece \
    && pip install --no-cache-dir whisperx \
    && pip install --no-cache-dir "/app/packages/transcript-postprocess[ner]" \
    && pip install --no-cache-dir .

RUN mkdir -p /app/runtime \
    && chmod 0777 /app/runtime \
    && chown -R whisperx:whisperx /app /home/whisperx

VOLUME ["/app/runtime"]

USER whisperx

ENTRYPOINT ["python", "-m", "whisperx_daemon"]
CMD ["--runtime-dir", "/app/runtime", "--once", "--model", "small", "--device", "cuda", "--compute-type", "float16"]
