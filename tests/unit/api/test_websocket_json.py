import uuid
from datetime import datetime
from enum import StrEnum

import pytest

from spectra_mission.core.websocket import ConnectionManager


class _TestEnum(StrEnum):
    TEST = "test"


@pytest.mark.asyncio
async def test_broadcast_event_serialization():
    # Setup
    manager = ConnectionManager()

    # Data with complex types
    complex_data = {
        "id": uuid.uuid4(),
        "timestamp": datetime.now(),
        "status": _TestEnum.TEST,
        "nested": {"id": uuid.uuid4()},
    }

    # Action
    # This should fail if standard json.dumps is used without defaults
    try:
        await manager.broadcast_event("test_event", complex_data)
    except TypeError as e:
        pytest.fail(f"Serialization failed: {e}")
    except Exception:
        # Other errors (like connection loop stuff) are ignored for this unit test
        # purely checking json.dumps inside
        pass
