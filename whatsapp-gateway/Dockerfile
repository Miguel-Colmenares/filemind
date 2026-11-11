# Puente de WhatsApp (Node + whatsapp-web.js) con el Chromium del sistema.
# La sesión vinculada vive en /gateway/.wwebjs_auth: móntala en un volumen persistente
# o habrá que escanear el código QR cada vez que se recree el contenedor.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium fonts-liberation fonts-noto-color-emoji ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    NODE_ENV=production

WORKDIR /gateway
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .

CMD ["node", "index.js"]
