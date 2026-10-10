from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def real_addons_dir() -> Path:
    return REPO_ROOT / "addons"


@pytest.fixture
def fixture_addons_dir():
    def _get(name: str) -> Path:
        return FIXTURES / name / "addons"

    return _get
