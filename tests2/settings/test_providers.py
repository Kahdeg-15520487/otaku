"""The provider sections' pure part: `render` writes providers.toml —
one top-level [name] section per provider, round-trip exact."""

import tomllib

from otaku2.settings.providers import ProviderConfig, render


class TestRender:
    def test_one_top_level_section_per_provider(self) -> None:
        providers = {
            "omlx": ProviderConfig(name="omlx", url="http://localhost:8100/v1", api_key="k"),
            "ollama": ProviderConfig(name="ollama", url="http://localhost:11434/v1"),
        }
        parsed = tomllib.loads(render(providers))
        assert set(parsed) == {"omlx", "ollama"}
        assert parsed["omlx"]["url"] == "http://localhost:8100/v1"
        assert parsed["omlx"]["api_key"] == "k"

    def test_keep_alive_appears_only_when_set(self) -> None:
        with_it = render({"a": ProviderConfig(name="a", url="x", keep_alive="24h")})
        assert 'keep_alive = "24h"' in with_it
        assert "keep_alive" not in render({"a": ProviderConfig(name="a", url="x")})
