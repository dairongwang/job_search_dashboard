"""Shared fixtures: isolated config path + offline HTTP transport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Every test gets its own site registry file (seeded with the built-in list)."""
    monkeypatch.setenv(jc.ENV_REGISTRY_VAR, str(tmp_path / "registry.json"))


@pytest.fixture
def config_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "cfg.json"
    monkeypatch.setenv(jc.ENV_PATH_VAR, str(path))
    return path


@pytest.fixture
def config(config_path) -> jc.AppConfig:
    cfg = jc.default_config()
    cfg.preferences.locations = ["United States", "Philadelphia, PA"]
    return cfg


class FakeTransport:
    """Serve canned responses keyed by a substring of the URL; records requests."""

    def __init__(self, responses: dict[str, bytes | str | dict | list | Exception]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.bodies: list[bytes | None] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: int, data: bytes | None = None) -> bytes:
        self.calls.append((url, headers))
        self.bodies.append(data)
        for needle, payload in self.responses.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                if isinstance(payload, (dict, list)):
                    return json.dumps(payload).encode()
                if isinstance(payload, str):
                    return payload.encode()
                return payload
        raise js.FetchError(f"no fixture for {url}")


@pytest.fixture
def transport():
    created: list[FakeTransport] = []

    def factory(responses):
        fake = FakeTransport(responses)
        js.set_fetcher(fake)
        created.append(fake)
        return fake

    yield factory
    js.set_fetcher(None)


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
