# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest.mock as mock

import pytest
from lightkube import ApiError


@pytest.fixture(autouse=True)
def lk_client():
    with mock.patch("ops.manifests.manifest.Client", autospec=True) as mock_lightkube:
        yield mock_lightkube.return_value


@pytest.fixture(autouse=True)
def lk_nad_client():
    with mock.patch("net_attach_definitions.Client", autospec=True) as mock_lightkube:
        yield mock_lightkube.return_value


@pytest.fixture()
def api_error_class():
    class TestApiError(ApiError):
        status = mock.MagicMock()

        def __init__(self):
            pass

    yield TestApiError


class MockActionEvent:
    def __init__(self, params):
        self.params = params
