# PTK backend: FastAPI + composition/QC/PPTX engine + LibreOffice preview renderer in one image.
# Previews render inside the container (RENDER_BACKEND=local), so no Docker socket is needed.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RENDER_BACKEND=local UNO_PYTHON=/usr/bin/python3
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-impress python3-uno poppler-utils fontconfig curl \
 && rm -rf /var/lib/apt/lists/*
COPY templates/fonts/ /usr/share/fonts/truetype/ptk/
RUN fc-cache -f && fc-list | grep -qi pretendard && fc-list | grep -qi "noto sans kr"

WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-cache-dir --no-deps -e . \
 && install -m 0755 infra/render/convert.py /usr/local/bin/convert.py

# DB (SQLite), uploaded files and outputs live here; mount it to keep data across containers.
VOLUME ["/app/var"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
