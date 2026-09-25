import os

from hehelohe.output import export_csv


def test_csv_export_with_mixed_row_shapes(tmp_path, monkeypatch):
    """Rows with inconsistent keys must not crash DictWriter (issue #231)."""
    monkeypatch.chdir(tmp_path)
    data = [
        {"name": "erratic", "domain": "erratic.io", "rateLimit": False,
         "error": True, "exists": False, "emailrecovery": None,
         "phoneNumber": None, "others": None},                      # error row
        {"name": "normal", "domain": "normal.io", "method": "register",
         "frequent_rate_limit": False, "rateLimit": False, "exists": True,
         "emailrecovery": None, "phoneNumber": None, "others": None},
    ]
    filename = export_csv(data, "user@example.com")
    content = open(filename, encoding="utf8").read()
    assert "erratic" in content and "normal" in content
    header = content.splitlines()[0]
    assert "method" in header and "error" in header
    os.remove(filename)


def test_csv_export_uses_prefix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = [{"name": "x", "domain": "x.io", "exists": False}]
    filename = export_csv(data, "u@e.io", prefix="hehelohe")
    assert filename.startswith("hehelohe_")
    assert filename.endswith("_u@e.io_results.csv")
