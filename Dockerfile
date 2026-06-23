# Hugging Face Spaces — Streamlit via Docker (native Streamlit SDK deprecated 2025-04)
# https://huggingface.co/docs/hub/spaces-changelog
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

USER user
WORKDIR /home/user/app

ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV PYTHONUNBUFFERED=1
ENV PATH="/home/user/.local/bin:${PATH}"

COPY --chown=user:user requirements.txt requirements-dashboard.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
