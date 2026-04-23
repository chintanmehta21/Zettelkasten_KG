import subprocess

import pytest

from ops.scripts.lib import server_manager


def test_start_server_reuses_existing_healthy_server(monkeypatch):
    monkeypatch.setattr(server_manager, "_is_healthy", lambda port: True)

    def fail_popen(*args, **kwargs):
        raise AssertionError("Popen should not be called for an already healthy server")

    monkeypatch.setattr(subprocess, "Popen", fail_popen)

    proc = server_manager.start_server(port=10000)
    server_manager.stop_server(proc)


def test_start_server_reports_early_process_exit(monkeypatch):
    class Stdout:
        def read(self):
            return b"bind failed"

    class Proc:
        stdout = Stdout()
        returncode = 1

        def poll(self):
            return self.returncode

    monkeypatch.setattr(server_manager, "_is_healthy", lambda port: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Proc())

    with pytest.raises(RuntimeError, match="exited before becoming healthy"):
        server_manager.start_server(port=10000)
