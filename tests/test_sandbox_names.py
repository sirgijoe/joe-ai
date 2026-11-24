"""Windows device names (including the superscript-digit and console ones) can't be used as file names."""
import pytest

from joeai.sandbox import Sandbox, SandboxError


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path / "ws").ensure()


@pytest.mark.parametrize("name", ["COM¹.txt", "conin$", "LPT².md", "CONOUT$.log", "com³", "lpt³.txt",
                                  "LPT¹", "COM².csv", "Output/CONIN$.txt"])
def test_device_names_refused(sb, name):
    with pytest.raises(SandboxError):
        sb.resolve(name)


@pytest.mark.parametrize("name", ["console.txt", "com.txt", "conin.txt", "lpt4x.md"])
def test_ordinary_names_allowed(sb, name):
    assert sb.resolve(name).name == name
