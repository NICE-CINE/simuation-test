from festival_ble_sim import archive


def test_stems_created_in_the_same_second_do_not_collide(tmp_path, monkeypatch):
    class FrozenNow:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime(2026, 10, 12, 10, 0, 0)

    monkeypatch.setattr(archive, "datetime", FrozenNow)
    first = archive.archive_stem(str(tmp_path), "epidemic")
    second = archive.archive_stem(str(tmp_path), "epidemic")
    assert first.name == "2026-10-12_10-00-00_epidemic"
    assert second.name == "2026-10-12_10-00-00_epidemic-2"
