# Test Framework — Fixes & Design Considerations

**Status:** step 1 of the exercise — make `main.py` work. `main.py` now starts the three emulators and receives one current reading from each.

Per the assignment: use the existing ammeter emulation infrastructure; if there is an error in the code, fix it and explain the fix in the documentation.

## Fixes

| # | Bug | Explanation of the fix |
|---|---|---|
| 1 | Second run fails with `Address already in use` (`Errno 48`). | The emulator closes each connection it serves, so the OS keeps that port reserved for about 30 seconds (`TIME_WAIT`). The next run's `bind()` refuses it. Fixed by setting `SO_REUSEADDR` before `bind()`, which lets a new server start right away; a program that is really listening on the port still gets `Errno 48`, so real conflicts are not hidden. |
| 2 | All three ammeters answered `No data received.` | `main.py` sent only the beginning of each command (`b'MEASURE_GREENLEE'`, `b'MEASURE_ENTES'`, `b'MEASURE_CIRCUTOR'`). The emulator compares the request byte-for-byte with its own command and closes the connection without replying when it does not match. Fixed by sending the complete command for each ammeter: `MEASURE_GREENLEE -get_measurement`, `MEASURE_ENTES -get_data`, `MEASURE_CIRCUTOR -get_measurement -current`. |
| 3 | An unrecognised command was ignored: the server closed the connection without a word, so the client could not tell a wrong request from a missing reply. | The server had no branch for a non-matching request. Added one: it now answers `ERR_UNKNOWN_COMMAND` and logs the received bytes, and the client prints that error instead of treating it as a measurement. An empty request is skipped instead of being answered. A wrong command is now reported as an error rather than as silence. |
| 4 | Ports and commands were hard-coded in `main.py` while `config/config.yaml` sat unused with its ammeter block commented out. | The config file is now the single source of truth: `main.py` reads each ammeter's port and command from it instead of repeating the values. At start-up each configured command is compared with the command the emulator actually accepts, so a mismatch stops the run immediately instead of quietly producing `ERR_UNKNOWN_COMMAND` later. |
| 5 | `load_config()` gave a raw traceback for a missing, empty or malformed config file. | It now raises a clear error for each case: `FileNotFoundError` with the path, `ValueError` with the YAML parsing problem, and `ValueError` when the file is empty or is not a mapping. A valid file still returns the parsed mapping. |

## Design considerations

| # | Decision | Rationale |
|---|---|---|
