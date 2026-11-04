"""Graphics detection without the real cards: fake /sys files, fake registry rows."""
from pathlib import Path

from joeai import hardware


def _sys_card(root: Path, n: int, vendor: str, vram_bytes=None, used=None, busy=None, temp=None):
    dev = root / f"card{n}" / "device"
    dev.mkdir(parents=True)
    (dev / "vendor").write_text(vendor + "\n")
    if vram_bytes is not None:
        (dev / "mem_info_vram_total").write_text(str(vram_bytes))
    if used is not None:
        (dev / "mem_info_vram_used").write_text(str(used))
    if busy is not None:
        (dev / "gpu_busy_percent").write_text(str(busy))
    if temp is not None:
        (dev / "hwmon" / "hwmon3").mkdir(parents=True)
        (dev / "hwmon" / "hwmon3" / "temp1_input").write_text(str(temp * 1000))
    (root / f"card{n}-HDMI-A-1").mkdir()                     # an output, never a card
    return dev


def test_linux_finds_amd_and_its_live_readings(tmp_path):
    _sys_card(tmp_path, 0, "0x8086")
    dev = _sys_card(tmp_path, 1, "0x1002", 16 * 1024 ** 3, used=2 * 1024 ** 3, busy=37, temp=61)
    cards = hardware.linux_cards(tmp_path)
    assert [c["vendor"] for c in cards] == ["intel", "amd"]
    assert cards[1]["total_mb"] == 16384
    live = hardware._amd_live(dev)
    assert live == {"vram_used_mb": 2048, "util_pct": 37, "temp_c": 61}


def test_linux_ignores_nvidia_and_unknown_cards(tmp_path):
    _sys_card(tmp_path, 0, "0x10de", 8 * 1024 ** 3)           # nvidia-smi covers these
    _sys_card(tmp_path, 1, "0x1af4")
    assert hardware.linux_cards(tmp_path) == []
    assert hardware.linux_cards(tmp_path / "missing") == []


def test_vendor_names():
    assert hardware.vendor_of("NVIDIA GeForce RTX 4070") == "nvidia"
    assert hardware.vendor_of("AMD Radeon RX 7800 XT") == "amd"
    assert hardware.vendor_of("Intel(R) Arc(TM) A770 Graphics") == "intel"
    assert hardware.vendor_of("Intel(R) UHD Graphics 770") == "intel"
    assert hardware.vendor_of("Matrox G200") == "other"


def test_windows_picks_the_real_card_over_the_built_in_chip(monkeypatch):
    monkeypatch.setattr(hardware, "windows_cards", lambda: [
        {"name": "Intel(R) UHD Graphics 770", "total_mb": 128},
        {"name": "Microsoft Basic Display Adapter", "total_mb": None},
        {"name": "AMD Radeon RX 7800 XT", "total_mb": 16368}])
    g = hardware._windows()
    assert g["vendor"] == "amd" and g["vram_total_mb"] == 16368 and g["temp_c"] is None


def test_windows_built_in_chip_has_no_card_memory(monkeypatch):
    monkeypatch.setattr(hardware, "windows_cards", lambda: [{"name": "Intel(R) Iris(R) Xe", "total_mb": 128}])
    g = hardware._windows()
    assert g["vendor"] == "intel" and g["vram_total_mb"] is None


def test_gpu_falls_back_when_there_is_no_nvidia_smi(monkeypatch):
    hardware.reset_cache()
    monkeypatch.setattr(hardware, "_nvidia", lambda: None)
    monkeypatch.setattr(hardware, "_static", lambda: hardware._card("AMD Radeon RX 6800", "amd", 16384))
    try:
        assert hardware.vendor() == "amd" and hardware.vram_total_gb() == 16.0
        assert hardware.gpu_temperature_c() is None                # no pause assumed
        assert not hardware.is_nvidia()
    finally:
        hardware.reset_cache()


def test_advice_is_honest_per_vendor():
    assert hardware.gpu_advice({"vendor": "nvidia"}) == ""
    assert "processor" in hardware.gpu_advice(None)
    amd_win = hardware.gpu_advice({"vendor": "amd", "temp_c": None}, "windows")
    assert "shaky" in amd_win and "pause is off" in amd_win
    assert "pause works" in hardware.gpu_advice({"vendor": "amd", "temp_c": 55}, "linux")
    mac = hardware.gpu_advice({"vendor": "apple", "unified": True})
    assert "shared" in mac and "slow" in mac
    assert "small model" in hardware.gpu_advice({"vendor": "intel"})
