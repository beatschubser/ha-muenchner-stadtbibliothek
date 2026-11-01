"""pytest setup for the Home Assistant tests (tests/test_integration.py).

Needs pytest-homeassistant-custom-component (installed in the GitHub workflow).
tests/test_client.py runs without it as well: python3 tests/test_client.py
"""

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # only the client tests can run
    collect_ignore = ["test_integration.py"]
else:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Allow Home Assistant to load custom_components/muenchner_stadtbibliothek in every test."""
        yield
