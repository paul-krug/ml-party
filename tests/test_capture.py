"""Hardware capture is part of the repro tuple, and it is the piece most
likely to quietly degrade on a platform nobody tested."""
import sys

import pytest

from mlparty.capture import capture_hardware


def test_hardware_capture_is_populated():
    hw = capture_hardware(captured_by="test")
    assert hw.host
    assert hw.platform
    assert hw.captured_by == "test"


@pytest.mark.skipif(sys.platform not in ("linux", "darwin"),
                    reason="RAM lookup is implemented for Linux and macOS")
def test_ram_is_captured_on_supported_platforms():
    assert capture_hardware().ram_gb, "ram_gb must not be empty on a supported platform"
