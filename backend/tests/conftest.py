import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Las pruebas de requisitos usan las categorías del documento de IA
os.environ["FILEMIND_PERFIL"] = "general"

from filemind.config import load_settings  # noqa: E402
from filemind.services.analysis_service import FileMind      # noqa: E402

GROUP = "Obra Vía Puerto Gaitán"


@pytest.fixture
def settings(tmp_path):
    s = load_settings(data_dir=tmp_path / "data", monitored_groups=[GROUP, "Compras Vichada"])
    s.ensure_dirs()
    src = ROOT / "data" / "modelos"
    for f in ("tema.joblib", "riesgo.joblib"):
        if (src / f).exists():
            shutil.copy(src / f, s.models_dir / f)
    return s


@pytest.fixture
def fm(settings):
    f = FileMind(settings)
    yield f
    f.shutdown()
