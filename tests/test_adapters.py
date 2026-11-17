"""T-05: one contract suite for three real adapters and the fake.

Run from the repository root:

    python -m unittest discover -s tests -v
"""

import io
import socket
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

from tests.emulator_helpers import free_port, start_emulator, wait_until_listening
from src.testing.adapters import FakeAmmeterAdapter, SocketAmmeterAdapter, build_adapters
from src.testing.errors import ConfigError, ParseError, ProtocolError, SampleTimeout, TransportError
from src.utils.config import load_config

CONFIG_PATH = "config/config.yaml"
CREATE_CONNECTION = "src.testing.adapters.socket_adapter.socket.create_connection"


class AdapterContractMixin:
    """Every adapter — real or fake — must pass exactly these tests."""

    def make_adapter(self):
        raise NotImplementedError

    def test_open_read_close_returns_float(self):
        adapter = self.make_adapter()
        adapter.open(timeout=2.0)
        try:
            self.assertTrue(adapter.is_open)
            self.assertIsInstance(adapter.read_current(), float)
        finally:
            adapter.close()
        self.assertFalse(adapter.is_open)

    def test_context_manager_opens_and_closes(self):
        adapter = self.make_adapter()
        with adapter as opened:
            self.assertIs(opened, adapter)
            self.assertTrue(adapter.is_open)
            self.assertIsInstance(adapter.read_current(), float)
        self.assertFalse(adapter.is_open)

    def test_read_before_open_raises_typed_error(self):
        adapter = self.make_adapter()
        with self.assertRaises(TransportError) as context:
            adapter.read_current()
        self.assertIn(adapter.name, str(context.exception))

    def test_read_after_close_raises_typed_error(self):
        adapter = self.make_adapter()
        adapter.open()
        adapter.close()
        with self.assertRaises(TransportError):
            adapter.read_current()

    def test_close_is_idempotent(self):
        adapter = self.make_adapter()
        adapter.close()
        adapter.open()
        adapter.close()
        adapter.close()
        self.assertFalse(adapter.is_open)

    def test_reopen_yields_another_reading(self):
        adapter = self.make_adapter()
        adapter.open()
        first = adapter.read_current()
        adapter.close()
        adapter.open()
        second = adapter.read_current()
        adapter.close()
        self.assertIsInstance(first, float)
        self.assertIsInstance(second, float)


class _SocketEmulatorContract(AdapterContractMixin):
    """Shared setup for the three real adapters against their frozen emulators."""

    emulator_class = None
    name_key = None

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        start_emulator(cls.emulator_class(cls.port))
        if not wait_until_listening(cls.port):
            raise AssertionError(f"{cls.name_key} emulator did not start on {cls.port}")

    def make_adapter(self):
        command = load_config(CONFIG_PATH)["ammeters"][self.name_key]["command"].encode("utf-8")
        return SocketAmmeterAdapter(self.name_key, self.port, command)


class TestGreenleeContract(_SocketEmulatorContract, unittest.TestCase):
    emulator_class = GreenleeAmmeter
    name_key = "greenlee"


class TestEntesContract(_SocketEmulatorContract, unittest.TestCase):
    emulator_class = EntesAmmeter
    name_key = "entes"


class TestCircutorContract(_SocketEmulatorContract, unittest.TestCase):
    emulator_class = CircutorAmmeter
    name_key = "circutor"


class TestFakeContract(AdapterContractMixin, unittest.TestCase):
    def make_adapter(self):
        return FakeAmmeterAdapter("fake", values=(1.25, 2.5))


class TestBuildAdapters(unittest.TestCase):
    def test_factory_builds_three_real_adapters_from_frozen_config(self):
        adapters = build_adapters(load_config(CONFIG_PATH), SocketAmmeterAdapter)
        self.assertEqual(set(adapters), {"greenlee", "entes", "circutor"})
        self.assertEqual(adapters["greenlee"].port, 5001)
        self.assertEqual(adapters["entes"].port, 5002)
        self.assertEqual(adapters["circutor"].port, 5003)
        self.assertEqual(adapters["circutor"].command, b"MEASURE_CIRCUTOR -get_measurement -current")

    def test_same_config_can_build_fakes(self):
        adapters = build_adapters(load_config(CONFIG_PATH), FakeAmmeterAdapter)
        self.assertEqual(set(adapters), {"greenlee", "entes", "circutor"})
        for adapter in adapters.values():
            self.assertIsInstance(adapter, FakeAmmeterAdapter)

    def test_missing_ammeters_raises_config_error(self):
        with self.assertRaises(ConfigError):
            build_adapters({}, SocketAmmeterAdapter)

    def test_invalid_port_raises_config_error(self):
        config = {"ammeters": {"x": {"port": 0, "command": "CMD"}}}
        with self.assertRaises(ConfigError):
            build_adapters(config, SocketAmmeterAdapter)


class TestSocketAdapterErrors(unittest.TestCase):
    def adapter_with_reply(self, reply: bytes):
        adapter = SocketAmmeterAdapter("circutor", 5003, b"CMD", timeout=0.5)
        connection = MagicMock()
        connection.recv.return_value = reply
        with patch(CREATE_CONNECTION, return_value=connection):
            adapter.open()
        return adapter, connection

    def test_dead_port_raises_transport_error_naming_endpoint(self):
        port = free_port()
        adapter = SocketAmmeterAdapter("greenlee", port, b"CMD")
        with self.assertRaises(TransportError) as context:
            adapter.open(timeout=0.2)
        message = str(context.exception)
        self.assertIn("greenlee", message)
        self.assertIn(str(port), message)
        self.assertIn("localhost", message)
        self.assertFalse(adapter.is_open)

    def test_recv_timeout_raises_sample_timeout(self):
        adapter = SocketAmmeterAdapter("entes", 5002, b"CMD", timeout=0.1)
        connection = MagicMock()
        connection.recv.side_effect = socket.timeout("deadline exceeded")
        with patch(CREATE_CONNECTION, return_value=connection):
            adapter.open()
            with self.assertRaises(SampleTimeout) as context:
                adapter.read_current()
        self.assertIn("entes", str(context.exception))
        adapter.close()

    def test_empty_reply_raises_protocol_error(self):
        adapter, _ = self.adapter_with_reply(b"")
        with self.assertRaises(ProtocolError):
            adapter.read_current()
        adapter.close()

    def test_error_marker_raises_protocol_error(self):
        adapter, _ = self.adapter_with_reply(b"ERR_UNKNOWN_COMMAND")
        with self.assertRaises(ProtocolError) as context:
            adapter.read_current()
        self.assertIn("ERR_UNKNOWN_COMMAND", str(context.exception))
        adapter.close()

    def test_non_numeric_reply_raises_parse_error(self):
        adapter, _ = self.adapter_with_reply(b"not-a-number")
        with self.assertRaises(ParseError):
            adapter.read_current()
        adapter.close()

    def test_nan_reply_raises_parse_error(self):
        adapter, _ = self.adapter_with_reply(b"nan")
        with self.assertRaises(ParseError):
            adapter.read_current()
        adapter.close()

    def test_context_manager_closes_the_socket_exactly_once(self):
        adapter = SocketAmmeterAdapter("greenlee", 5001, b"CMD")
        connection = MagicMock()
        connection.recv.return_value = b"1.5"
        with patch(CREATE_CONNECTION, return_value=connection):
            with adapter:
                self.assertEqual(adapter.read_current(), 1.5)
        connection.close.assert_called_once()
        self.assertFalse(adapter.is_open)

    def test_adapter_never_prints(self):
        adapter, _ = self.adapter_with_reply(b"1.0")
        output = io.StringIO()
        with redirect_stdout(output):
            adapter.read_current()
            adapter.close()
        self.assertEqual(output.getvalue(), "")


class TestNoThreadLeak(unittest.TestCase):
    def test_repeated_cycles_do_not_create_threads(self):
        port = free_port()
        start_emulator(GreenleeAmmeter(port))
        self.assertTrue(wait_until_listening(port))
        command = load_config(CONFIG_PATH)["ammeters"]["greenlee"]["command"].encode("utf-8")
        adapter = SocketAmmeterAdapter("greenlee", port, command)

        before = threading.active_count()
        for _ in range(5):
            with adapter:
                adapter.read_current()
        self.assertEqual(threading.active_count(), before)


class TestFakeAdapterExtras(unittest.TestCase):
    def test_injected_exception_is_raised_in_its_turn(self):
        boom = SampleTimeout("injected")
        adapter = FakeAmmeterAdapter("fake", values=(1.0, boom, 2.0))
        adapter.open()
        self.assertEqual(adapter.read_current(), 1.0)
        with self.assertRaises(SampleTimeout):
            adapter.read_current()
        self.assertEqual(adapter.read_current(), 2.0)
        self.assertEqual(adapter.reads, 3)
        adapter.close()

    def test_values_cycle_and_timeout_is_recorded(self):
        adapter = FakeAmmeterAdapter("fake", values=(3.0,))
        adapter.open(timeout=0.25)
        self.assertEqual([adapter.read_current() for _ in range(3)], [3.0, 3.0, 3.0])
        self.assertEqual(adapter.last_timeout, 0.25)
        adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
