from harness.private_leak_guard import (Blocklist, STATUS_BLOCKED,
                                        STATUS_PASS, check, load_blocklist,
                                        scan_text, scan_tree)

# Synthetic blocklist for tests — real terms live only in the gitignored file.
BL = Blocklist(terms=["internal-codename-orion", "project falcon"],
               filename_patterns=["orion_"])


def test_scan_text_finds_terms_case_insensitive():
    hits = scan_text("Notes on Internal-Codename-ORION here", BL.terms)
    assert hits and hits[0][0] == "internal-codename-orion"


def test_scan_text_clean():
    assert scan_text("a perfectly ordinary engineering note", BL.terms) == []


def test_scan_tree_flags_content_and_filenames(tmp_path):
    (tmp_path / "notes.md").write_text("mentions project falcon design")
    (tmp_path / "orion_adapter.py").write_text("x = 1")
    findings = scan_tree(tmp_path, BL)
    kinds = {(f.kind, f.location) for f in findings}
    assert ("content", "notes.md") in kinds
    assert ("filename", "orion_adapter.py") in kinds


def test_scan_tree_skips_private_dir(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "theory.md").write_text("project falcon everything")
    assert scan_tree(tmp_path, BL) == []


def test_check_status(tmp_path):
    (tmp_path / "ok.md").write_text("clean")
    assert check(tmp_path, blocklist=BL).status == STATUS_PASS
    (tmp_path / "leak.md").write_text("internal-codename-orion")
    assert check(tmp_path, blocklist=BL).status == STATUS_BLOCKED


def test_load_blocklist_falls_back_to_example(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "example_release_blocklist.yaml").write_text(
        "terms:\n  - sample-term\nfilename_patterns:\n  - sample_\n")
    bl = load_blocklist(tmp_path)
    assert bl.terms == ["sample-term"]
    assert bl.source.startswith("example:")


def test_load_blocklist_prefers_real_file(tmp_path):
    (tmp_path / ".private_release_blocklist.yaml").write_text(
        "terms:\n  - real-term\n")
    bl = load_blocklist(tmp_path)
    assert bl.terms == ["real-term"] and bl.source.startswith("real:")
