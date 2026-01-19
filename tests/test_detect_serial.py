from types import SimpleNamespace
import importlib
import lumina_head_tracker as lht


def make_port(device, description='', manufacturer=''):
    return SimpleNamespace(device=device, description=description, manufacturer=manufacturer)


def test_detect_serial_no_ports(monkeypatch):
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    assert lht.detect_serial_port(verbose=False) is None


def test_detect_serial_prefers_token(monkeypatch):
    p1 = make_port('/dev/ttyUSB0', 'USB Serial', 'Generic')
    p2 = make_port('/dev/tty.SLAB', 'CP210x USB to UART Bridge', 'Silicon Labs')
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [p1, p2])
    assert lht.detect_serial_port(verbose=False) == '/dev/tty.SLAB'


def test_detect_serial_fallback(monkeypatch):
    p1 = make_port('/dev/ttyUSB0', 'Generic', 'Generic')
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [p1])
    assert lht.detect_serial_port(verbose=False) == '/dev/ttyUSB0'


def test_detect_serial_pick_interactive(monkeypatch):
    p1 = make_port('/dev/tty.A', 'A', 'A')
    p2 = make_port('/dev/tty.B', 'B', 'B')
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [p1, p2])
    monkeypatch.setattr('builtins.input', lambda prompt='': '2')
    # simulate a TTY by monkeypatching sys.stdin.isatty
    monkeypatch.setattr('sys.stdin', SimpleNamespace(isatty=lambda: True))
    assert lht.detect_serial_port(verbose=False, pick=True) == '/dev/tty.B'
