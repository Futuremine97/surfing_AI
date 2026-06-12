from harness.backend_health import (SAFE_VOCAB, format_health,
                                    summarize_health)

FAKE_STATUSES = [
    {"backend": "claude", "installed": True, "authenticated": True,
     "key_present": False, "path": "/usr/local/bin/claude",
     "version": "claude 9.9.9", "auth_detail": "credentials file: /home/u"},
    {"backend": "codex", "installed": True, "authenticated": False,
     "key_present": True, "path": "/opt/codex", "version": "codex 1.2"},
    {"backend": "gemini", "installed": False, "authenticated": None,
     "key_present": False},
]


def test_safe_vocabulary_only():
    rows = summarize_health(statuses=FAKE_STATUSES)
    for row in rows:
        for key, value in row.items():
            if key == "backend":
                continue
            assert value in SAFE_VOCAB, (key, value)


def test_mapping():
    rows = {r["backend"]: r for r in summarize_health(statuses=FAKE_STATUSES)}
    assert rows["claude"] == {"backend": "claude", "binary": "present",
                              "auth": "ok", "api_key": "missing"}
    assert rows["codex"]["auth"] == "failed"
    assert rows["codex"]["api_key"] == "present"
    assert rows["gemini"] == {"backend": "gemini", "binary": "missing",
                              "auth": "not_configured",
                              "api_key": "missing"}


def test_no_paths_versions_or_details_leak():
    rows = summarize_health(statuses=FAKE_STATUSES)
    text = format_health(rows)
    for leak in ("/usr/local/bin", "9.9.9", "/opt/codex", "credentials",
                 "/home/u"):
        assert leak not in text
    # only the four safe fields exist per row
    assert all(set(r) == {"backend", "binary", "auth", "api_key"}
               for r in rows)


def test_missing_binary_means_not_configured():
    rows = summarize_health(statuses=[{"backend": "x", "installed": False,
                                       "authenticated": True,
                                       "key_present": True}])
    assert rows[0]["auth"] == "not_configured"
