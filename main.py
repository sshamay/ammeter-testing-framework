import threading
import time

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.utils.config import load_config

CONFIG_PATH = "config/config.yaml"

# Ammeter name in config/config.yaml -> emulator class
AMMETERS = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def build_emulators(config):
    """Create one emulator per configured ammeter and check the config matches the code."""
    emulators = {}
    for name, ammeter_class in AMMETERS.items():
        settings = config["ammeters"][name]
        emulator = ammeter_class(settings["port"])
        configured = settings["command"].encode("utf-8")
        if configured != emulator.get_current_command:
            raise SystemExit(
                f"Config command for {name} is {configured!r}, "
                f"but the emulator expects {emulator.get_current_command!r}"
            )
        emulators[name] = emulator
    return emulators


def main():
    config = load_config(CONFIG_PATH)
    emulators = build_emulators(config)

    # Start each ammeter in a separate thread
    for emulator in emulators.values():
        threading.Thread(target=emulator.start_server, daemon=True).start()

    # Give the servers time to open their ports before the first request.
    time.sleep(5)

    for name, emulator in emulators.items():
        command = config["ammeters"][name]["command"].encode("utf-8")
        request_current_from_ammeter(emulator.port, command)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
