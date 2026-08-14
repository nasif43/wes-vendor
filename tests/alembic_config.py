from pathlib import Path

from alembic.config import Config

ALEMBIC_CFG = Config(str(Path(__file__).parent.parent / "alembic.ini"))
