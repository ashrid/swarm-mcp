"""tmux management using libtmux with a mock fallback for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class TmuxLike(Protocol):
    def spawn_worker(self, agent_id: str, command: str) -> str: ...
    def kill_worker(self, agent_id: str) -> None: ...
    def send_keys(self, agent_id: str, text: str, enter: bool = True) -> None: ...
    def capture_pane(self, agent_id: str, start: str | int = "-") -> str: ...
    def is_alive(self, agent_id: str) -> bool: ...
    def list_workers(self) -> dict[str, str]: ...
    def cleanup_all(self) -> None: ...


@dataclass
class MockPane:
    command: str
    content: list[str] = field(default_factory=list)
    alive: bool = True


class MockTmuxManager:
    def __init__(self, session_name: str = "swarm-test") -> None:
        self.session_name = session_name
        self._panes: dict[str, MockPane] = {}

    def spawn_worker(self, agent_id: str, command: str) -> str:
        pane_id = f"{self.session_name}:{agent_id}"
        self._panes[agent_id] = MockPane(command=command, content=[command])
        return pane_id

    def kill_worker(self, agent_id: str) -> None:
        if agent_id in self._panes:
            self._panes[agent_id].alive = False

    def send_keys(self, agent_id: str, text: str, enter: bool = True) -> None:
        pane = self._panes[agent_id]
        pane.content.append(text + ("\n" if enter else ""))

    def capture_pane(self, agent_id: str, start: str | int = "-") -> str:
        pane = self._panes[agent_id]
        return "\n".join(line.rstrip("\n") for line in pane.content)

    def is_alive(self, agent_id: str) -> bool:
        return self._panes.get(agent_id, MockPane(command="", alive=False)).alive

    def list_workers(self) -> dict[str, str]:
        return {
            agent_id: ("alive" if pane.alive else "dead")
            for agent_id, pane in self._panes.items()
        }

    def spawn_dashboard(self, swarm_dir: str, refresh_interval: int = 5) -> str:
        pane_id = f"{self.session_name}:swarm-dashboard"
        self._panes["swarm-dashboard"] = MockPane(
            command=f"dashboard {swarm_dir} {refresh_interval}",
            content=[f"Dashboard rendering every {refresh_interval}s"],
        )
        return pane_id

    def cleanup_all(self) -> None:
        for pane in self._panes.values():
            pane.alive = False


class TmuxManager:
    def __init__(self, session_name: str, socket_name: str = "swarm", mock: bool = False) -> None:
        self.session_name = session_name
        self.socket_name = socket_name
        self.mock = mock
        self._mock_impl = MockTmuxManager(session_name=session_name) if mock else None

    def _server(self) -> Any:
        if self.mock:
            raise RuntimeError("Mock mode should not call real tmux server")
        import libtmux

        return libtmux.Server(socket_name=self.socket_name)

    def _ensure_session(self) -> Any:
        server = self._server()
        session = server.find_where({"session_name": self.session_name})
        if session is None:
            session = server.new_session(
                session_name=self.session_name,
                attach=False,
                kill_session=True,
            )
            session.set_option("history-limit", "100000")
        return session

    def spawn_worker(self, agent_id: str, command: str) -> str:
        if self.mock:
            assert self._mock_impl is not None
            return self._mock_impl.spawn_worker(agent_id, command)

        session = self._ensure_session()
        window = session.attached_window or session.windows[0]
        pane = window.attached_pane or window.panes[0]
        if window.panes:
            pane = pane.split(attach=False)
        pane.cmd("select-pane", "-T", agent_id)
        pane.send_keys(command, enter=True, literal=True)
        return str(pane.pane_id)

    def _find_pane(self, agent_id: str) -> Any:
        session = self._ensure_session()
        for window in session.windows:
            for pane in window.panes:
                title = pane.display_message("#{pane_title}")
                if title == agent_id:
                    return pane
        raise KeyError(f"Worker pane not found: {agent_id}")

    def kill_worker(self, agent_id: str) -> None:
        if self.mock:
            assert self._mock_impl is not None
            self._mock_impl.kill_worker(agent_id)
            return
        self._find_pane(agent_id).kill()

    def send_keys(self, agent_id: str, text: str, enter: bool = True) -> None:
        if self.mock:
            assert self._mock_impl is not None
            self._mock_impl.send_keys(agent_id, text, enter=enter)
            return
        self._find_pane(agent_id).send_keys(text, enter=enter, literal=True)

    def capture_pane(self, agent_id: str, start: str | int = "-") -> str:
        if self.mock:
            assert self._mock_impl is not None
            return self._mock_impl.capture_pane(agent_id, start=start)
        pane = self._find_pane(agent_id)
        lines = pane.capture_pane(start=start, end="-")
        return "\n".join(line.rstrip() for line in lines)

    def is_alive(self, agent_id: str) -> bool:
        if self.mock:
            assert self._mock_impl is not None
            return self._mock_impl.is_alive(agent_id)
        try:
            self._find_pane(agent_id)
            return True
        except KeyError:
            return False

    def list_workers(self) -> dict[str, str]:
        if self.mock:
            assert self._mock_impl is not None
            return self._mock_impl.list_workers()
        session = self._ensure_session()
        workers: dict[str, str] = {}
        for window in session.windows:
            for pane in window.panes:
                title = pane.display_message("#{pane_title}")
                if title:
                    workers[str(title)] = str(pane.pane_id)
        return workers

    def spawn_dashboard(self, swarm_dir: str, refresh_interval: int = 5) -> str:
        import shlex

        if self.mock:
            assert self._mock_impl is not None
            return self._mock_impl.spawn_dashboard(swarm_dir, refresh_interval)
        session = self._ensure_session()
        window = session.attached_window or session.windows[0]
        pane = window.attached_pane or window.panes[0]
        if window.panes:
            pane = pane.split(attach=False)
        pane.cmd("select-pane", "-T", "swarm-dashboard")
        clamped_refresh = max(1, min(refresh_interval, 60))
        env = f"SWARM_DASHBOARD_REFRESH={clamped_refresh}"
        command = (
            f"{env} python3 -m swarm_mcp.dashboard_renderer {shlex.quote(swarm_dir)}"
        )
        pane.send_keys(command, enter=True, literal=True)
        return str(pane.pane_id)

    def cleanup_all(self) -> None:
        if self.mock:
            assert self._mock_impl is not None
            self._mock_impl.cleanup_all()
            return
        server = self._server()
        session = server.find_where({"session_name": self.session_name})
        if session is not None:
            session.kill_session()
