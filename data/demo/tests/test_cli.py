import pytest

from data.demo.__main__ import main
from data.demo.fetch import DownloadUnavailable, IntegrityError


def test_up_demo_falls_back_only_when_download_is_unavailable(monkeypatch, capsys):
    def unavailable(*args):
        raise DownloadUnavailable("Réseau indisponible")

    monkeypatch.setattr("data.demo.__main__.prepared_dataset", unavailable)
    monkeypatch.setattr("sys.argv", ["data.demo", "up-demo"])
    assert main() == 0
    assert "fixtures locales" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["fetch", "load", "up-demo"])
def test_integrity_errors_remain_failures_in_all_commands(monkeypatch, action):
    def corrupt(*args):
        raise IntegrityError("SHA-256 incorrect")

    monkeypatch.setattr("data.demo.__main__.prepared_dataset", corrupt)
    monkeypatch.setattr("sys.argv", ["data.demo", action])
    assert main() == 1
