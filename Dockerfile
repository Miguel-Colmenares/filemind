# Imagen única: compila la interfaz React y la sirve desde la API de Python.
FROM node:20-bookworm-slim AS interfaz
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app/backend
RUN apt-get update && apt-get install -y --no-install-recommends util-linux docker-cli \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=interfaz /src/frontend/dist /app/frontend/dist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["python", "-m", "filemind", "serve", "--host", "0.0.0.0", "--port", "8000"]
