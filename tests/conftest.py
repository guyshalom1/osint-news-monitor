"""Shared test setup."""

import pytest

from osint_monitor import entities


@pytest.fixture(autouse=True)
def regex_entities_by_default():
    """Tests run on the regex extractor unless they choose spaCy, so results
    do not depend on whether the model is installed."""
    entities.use_backend("regex")
    yield
    entities.use_backend("regex")
