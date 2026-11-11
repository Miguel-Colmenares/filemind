"""Registro de disponibilidad (RNF2: >= 98 % del tiempo mensual).

Un hilo escribe un latido cada 30 s (se cuenta un minuto si tuvo al menos uno) en ``data/uptime.log`` (una marca de
minuto por línea). La disponibilidad del mes = minutos con latido / minutos
transcurridos del mes desde el primer arranque registrado. Para producción se
recomienda además un monitor externo (p. ej. Uptime Kuma) contra ``/health``
y la política ``restart: unless-stopped`` del docker-compose.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class UptimeMonitor:
    def __init__(self, path: Path, interval: int = 30):
        self.path, self.interval = Path(path), interval
        self._stop = threading.Event()
        self.started = time.time()

    def _beat(self):
        minute = int(time.time() // 60)
        with open(self.path, "a") as fh:
            fh.write(f"{minute}\n")

    def start(self):
        def loop():
            while not self._stop.is_set():
                self._beat()
                self._stop.wait(self.interval)
        threading.Thread(target=loop, daemon=True, name="uptime").start()

    def stop(self):
        self._stop.set()

    def report(self, now: float | None = None) -> dict:
        now = now or time.time()
        dt = datetime.fromtimestamp(now, timezone.utc)
        month_start = int(datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).timestamp() // 60)
        cur = int(now // 60)
        minutes = set()
        if self.path.exists():
            for line in self.path.read_text().split():
                m = int(line)
                if month_start <= m <= cur:
                    minutes.add(m)
        if not minutes:
            return {"mes": dt.strftime("%Y-%m"), "disponibilidad": None, "minutos_activos": 0}
        first = min(minutes)
        last = cur if cur in minutes else cur - 1   # el minuto en curso aún puede recibir su latido
        total = max(last - first + 1, 1)
        pct = 100 * len(minutes) / total
        return {"mes": dt.strftime("%Y-%m"), "desde_minuto": first, "minutos_observados": total,
                "minutos_activos": len(minutes), "disponibilidad": round(pct, 3), "rnf2_cumple": pct >= 98.0}
