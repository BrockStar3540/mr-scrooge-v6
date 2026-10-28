"""B-145: the dashboard listen queue must outlast routine pollers."""
import inspect

import ops.server as server


def test_dashboard_listen_queue_is_wide():
    src = inspect.getsource(server)
    assert "request_queue_size = 64" in src
