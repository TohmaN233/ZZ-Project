from zz.web.assets import AssetIndex


class _FakeAssetIndex:
    _mana_asset_ids = {"RED": "mana_RED", "COLORLESS": "mana_COLORLESS"}

    def mana_asset_url(self, color: str) -> str:
        return f"/assets/{self._mana_asset_ids[color]}"


def test_mana_asset_catalog_reuses_registered_local_asset_urls() -> None:
    catalog = AssetIndex.mana_asset_catalog(_FakeAssetIndex())

    assert catalog == {
        "COLORLESS": "/assets/mana_COLORLESS",
        "RED": "/assets/mana_RED",
    }
