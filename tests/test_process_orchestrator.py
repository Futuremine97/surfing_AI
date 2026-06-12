from harness.process_orchestrator import (ParallelRunner,
                                          manual_terminal_commands,
                                          max_processes)
from harness.tmux_adapter import build_grid_commands, launch_grid


def test_max_processes_at_least_one():
    assert max_processes() >= 1
    assert max_processes(reserve=10_000) == 1


def test_parallel_run_distributes_and_executes(tmp_path):
    runner = ParallelRunner(root=tmp_path, workers=3)
    commands = [f"echo job{i}" for i in range(7)]
    results = runner.run(commands)
    runner.close()
    assert len(results) == 7
    assert {r["worker"] for r in results} == {0, 1, 2}
    for i, result in enumerate(sorted(results, key=lambda r: r["index"])):
        assert result["output"] == f"job{i}"
        assert not result["blocked"]


def test_parallel_run_keeps_invariants(tmp_path):
    runner = ParallelRunner(root=tmp_path, workers=2)
    results = runner.run(["echo ok", "git push origin main",
                          "rm -rf build", ":ask claude hello"])
    totals = runner.aggregate_counters()
    runner.close()
    by_cmd = {r["command"]: r for r in results}
    assert not by_cmd["echo ok"]["blocked"]
    assert by_cmd["git push origin main"]["blocked"]
    assert by_cmd["rm -rf build"]["blocked"]
    assert by_cmd[":ask claude hello"]["blocked"]  # external OFF
    assert totals["files_sent_external"] == 0
    assert totals["external_backend_calls"] == 0
    assert totals["blocked_commands"] == 3


def test_workers_have_separate_audit_dirs(tmp_path):
    runner = ParallelRunner(root=tmp_path, workers=4)
    dirs = {terminal.audit.dir for terminal in runner.terminals}
    runner.close()
    assert len(dirs) == 4


def test_manual_terminal_commands():
    commands = manual_terminal_commands(panes=3, mode="audit")
    assert len(commands) == 3
    assert all("terminal-private --mode audit" in c for c in commands)


def test_build_grid_commands_pane_count(tmp_path):
    commands = build_grid_commands("grid", tmp_path, panes=4)
    splits = [c for c in commands if c[:2] == ["tmux", "split-window"]]
    tiles = [c for c in commands if c[:2] == ["tmux", "select-layout"]]
    assert commands[0][:2] == ["tmux", "new-session"]
    assert len(splits) == 3 and len(tiles) == 3


def test_launch_grid_never_hard_fails(tmp_path):
    result = launch_grid(root=tmp_path, panes=2, dry_run=True)
    assert result["status"] in ("DRY_RUN", "TMUX_NOT_FOUND")
    if result["status"] == "TMUX_NOT_FOUND":
        assert len(result["manual_commands"]) == 2
    else:
        assert len(result["commands"]) == 3  # new-session + split + layout
