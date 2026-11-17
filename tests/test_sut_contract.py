"""T-10: SUT contract and accuracy tests (F-14…F-26 from the archived spec).

No supplied file is changed. Values are asserted exactly only where the test injects the operands;
unmocked generator draws are checked against their documented bounds.
"""

import io
import socket
import unittest
from contextlib import redirect_stdout
from unittest.mock import call, patch

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.utils.Utils import generate_random_float
from tests.emulator_helpers import free_port, start_emulator, wait_until_listening


def ask(port: int, command: bytes, timeout: float = 3.0) -> bytes:
    with socket.create_connection(("localhost", port), timeout=timeout) as connection:
        connection.sendall(command)
        return connection.recv(1024)


def record_draws(original, drawn):
    """Keep the real draw but remember the value it returned — the SUT's operand."""

    def record(*args, **kwargs):
        value = original(*args, **kwargs)
        drawn.append(value)
        return value

    return record


class TestMeasurementBounds(unittest.TestCase):
    """F-14…F-16: unmocked draws can only be checked against documented bounds."""

    def test_greenlee_bounds(self):
        emulator = GreenleeAmmeter(free_port())
        with redirect_stdout(io.StringIO()):
            values = [emulator.measure_current() for _ in range(50)]
        for value in values:
            with self.subTest(value=value):
                self.assertGreaterEqual(value, 0.01)
                self.assertLessEqual(value, 100)

    def test_entes_bounds(self):
        emulator = EntesAmmeter(free_port())
        with redirect_stdout(io.StringIO()):
            values = [emulator.measure_current() for _ in range(50)]
        for value in values:
            with self.subTest(value=value):
                self.assertGreaterEqual(value, 5)
                self.assertLessEqual(value, 200)

    def test_circutor_bounds(self):
        emulator = CircutorAmmeter(free_port())
        with redirect_stdout(io.StringIO()):
            values = [emulator.measure_current() for _ in range(50)]
        for value in values:
            with self.subTest(value=value):
                self.assertGreaterEqual(value, 0.001)
                self.assertLessEqual(value, 0.1)


class TestFormulaOracles(unittest.TestCase):
    """F-17…F-20: exact values are asserted only from operands this test supplies."""

    def test_greenlee_formula_from_recorded_draws(self):
        draws = []
        with patch(
            "Ammeters.Greenlee_Ammeter.generate_random_float",
            side_effect=record_draws(generate_random_float, draws),
        ) as mocked:
            with redirect_stdout(io.StringIO()):
                value = GreenleeAmmeter(free_port()).measure_current()

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(value, draws[0] / draws[1])
        mocked.assert_has_calls([call(1.0, 10.0), call(0.1, 100.0)])

    def test_entes_formula_from_recorded_draws(self):
        draws = []
        with patch(
            "Ammeters.Entes_Ammeter.generate_random_float",
            side_effect=record_draws(generate_random_float, draws),
        ) as mocked:
            with redirect_stdout(io.StringIO()):
                value = EntesAmmeter(free_port()).measure_current()

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(value, draws[0] * draws[1])
        mocked.assert_has_calls([call(0.01, 0.1), call(500, 2000)])

    def test_circutor_formula_from_recorded_draws(self):
        draws = []
        with patch(
            "Ammeters.Circutor_Ammeter.generate_random_float",
            side_effect=record_draws(generate_random_float, draws),
        ) as mocked:
            with redirect_stdout(io.StringIO()):
                value = CircutorAmmeter(free_port()).measure_current()

        self.assertEqual(mocked.call_count, 11)
        time_step, voltages = draws[0], draws[1:]
        self.assertEqual(value, sum(voltage * time_step for voltage in voltages))
        mocked.assert_has_calls([call(0.001, 0.01)] + [call(0.1, 1.0)] * 10)

    def test_injected_golden_values_and_call_order(self):
        with patch(
            "Ammeters.Greenlee_Ammeter.generate_random_float", side_effect=[10.0, 0.1]
        ) as mocked:
            with redirect_stdout(io.StringIO()):
                value = GreenleeAmmeter(free_port()).measure_current()

        self.assertEqual(value, 100.0)
        mocked.assert_has_calls([call(1.0, 10.0), call(0.1, 100.0)])

    def test_rng_helper_is_half_open(self):
        values = [generate_random_float(1.0, 10.0) for _ in range(200)]
        self.assertTrue(all(1.0 <= value < 10.0 for value in values))


class TestWireProtocol(unittest.TestCase):
    """F-21…F-24, F-26: behaviour over the frozen socket protocol."""

    def setUp(self):
        self.port = free_port()
        start_emulator(GreenleeAmmeter(self.port))
        self.assertTrue(wait_until_listening(self.port))

    def test_str_serialisation_round_trip_is_lossless(self):
        expected = 0.1 + 0.2
        with patch.object(GreenleeAmmeter, "measure_current", return_value=expected):
            self.assertEqual(float(ask(self.port, b"MEASURE_GREENLEE -get_measurement")), expected)

    def test_two_sequential_clients_both_get_numbers(self):
        for _ in range(2):
            reply = ask(self.port, b"MEASURE_GREENLEE -get_measurement")
            self.assertIsInstance(float(reply), float)

    def test_empty_payload_gets_no_reply(self):
        with socket.create_connection(("localhost", self.port), timeout=2) as connection:
            connection.shutdown(socket.SHUT_WR)
            self.assertEqual(connection.recv(1024), b"")

    def test_occupied_port_raises_os_error(self):
        port = free_port()  # a fresh port: setUp's emulator already owns self.port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("localhost", port))
            held.listen()
            with self.assertRaises(OSError):
                GreenleeAmmeter(port).start_server()

    def test_client_success_path_prints_measurement(self):
        output = io.StringIO()
        with redirect_stdout(output):
            request_current_from_ammeter(self.port, b"MEASURE_GREENLEE -get_measurement")
        self.assertIn("Received current measurement", output.getvalue())
        self.assertNotIn("Error from port", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
