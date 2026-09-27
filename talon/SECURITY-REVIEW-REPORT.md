# Line 4 OpenPLC Security Review — Report

**Talon Power Systems — Kingsport Engine Plant — Controls Engineering / OT Security**
Scope: the OpenPLC Runtime v3 fork in this repository as installed on PW-430 (Cell 4-30 washer controller), `webserver/` and `webserver/core/`, reviewed against `master` @ `915665c`. Companion to `talon/SECURITY-SWARM.md`, which holds the threat model, the peer-incident narrative and the seeded finding list. This report records what was confirmed, how it was rated, what was fixed, and what remains.

Method: every seeded finding was confirmed by reading the code and shipped database, rated with a CVSS v3.1 vector, and handed to an independent remediation session with the rule *one finding, one failing test, one PR*. Reproductions are pytest unit/integration tests under `talon/security-tests/` that fail on the unpatched tree and pass with the fix; no exploit code was written. Every PR was gated on the Line 4 SIL suite (`cd talon/L4-WASH-01/sil && make test` → 20 passed), so none of the fixes changes the `%I/%Q/%M` behaviour of `L4_WASH_01.st`.

## 1. Executive summary

PW-430 today is, in code terms, the same shape of device that was hit in the incidents the corporate cyber-risk committee cited:

- **Unitronics / CISA AA23-335A (Nov 2023).** The attackers needed nothing more than a reachable PLC web interface with the vendor default password. This runtime ships `openplc`/`openplc`, stores it in cleartext, compares it with `==`, and serves the login form over HTTP on every interface. On the cell VLAN the maintenance-laptop drop (TB-4-430) is live. Findings F1 and F6.
- **FrostyGoop / Dragos (Jan 2024).** The malware simply wrote holding registers over Modbus/TCP. Our setpoints `%MW0..5` are holding registers HR1024–1029 and the runtime accepts FC6/FC16 writes — and the OpenPLC debugger's "force variable" function code 0x42 — from any client that can reach port 502, with no source check. Finding F3.
- **Talos ENIP/PCCC advisories (2024).** The EtherNet/IP server with the CVE history is listening on 44818 for a consumer that left in 2022. The upstream parser fixes *are* in this tree; the port is still unnecessary attack surface. Finding F4.
- **Clorox, Johnson Controls, Halliburton, Sensata, Nucor, JLR.** Each is a story of an IT-side compromise that ended with plants stopped as a precaution. Everything on this controller that lets an authenticated web user run code (F2), traverse the filesystem (F7), or rename the host (F8), and every unauthenticated local control channel (F5), is a lateral-movement step from "someone phished an engineer whose laptop is on the cell VLAN" to "the washer is a bricked Linux box". Findings F2, F5, F7, F8, F9, F10.

Ten findings were confirmed (nine seeded, one added during triage). Two are Critical, six High, two Medium by CVSS; by the site rule in `SECURITY-SWARM.md` §5.6 (anything reachable from the cell VLAN without authentication that can change a setpoint or stop the runtime is Critical for this site), F3 and F4 are also treated as Critical for Line 4.

## 2. Findings

| ID | Finding | CWE | CVSS 3.1 | Advisory / CVE | PR | Status |
|---|---|---|---|---|---|---|
| F1 | Default `openplc`/`openplc` credential stored and compared in cleartext (`webserver.py` `login()`, `openplc.db` `Users`) | CWE-256, CWE-798, CWE-1392 | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H — **9.8** | CISA AA23-335A pattern | [#5](https://github.com/COG-GTM/OpenPLC_v3/pull/5) | Open, reviewed — `test_credentials.py` 7→0 failures, SIL 20/20 |
| F2 | Hardware-layer "code box" writes `core/psm/main.py` for any authenticated user (`webserver.py` `hardware()`) | CWE-94 | AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H — **9.9** | CVE-2021-31630 | [#8](https://github.com/COG-GTM/OpenPLC_v3/pull/8) | Open, reviewed — `test_psm_editing_gate.py` 5→0, SIL 20/20 |
| F3 | Unauthenticated Modbus/TCP writes (FC6/FC16, debug FC 0x42) to HR1024–1029 setpoints; server bound to `INADDR_ANY` (`core/modbus.cpp`, `core/server.cpp`) | CWE-306, CWE-862 | AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H — **8.1** (site: Critical) | FrostyGoop (Dragos); cf. SEVD-2024-317-03 | [#6](https://github.com/COG-GTM/OpenPLC_v3/pull/6) | Open, reviewed — `test_modbus_write_allowlist.py` 9→0, SIL 20/20 |
| F4 | ENIP/PCCC server enabled by default (`Enip_port=44818`) with no consumer; auto-started at boot (`webserver.py` startup, `openplc.db` `Settings`) | CWE-1188 | AV:A/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:H — **7.6** (site: Critical) | CVE-2024-34026 (TALOS-2024-2005), CVE-2024-36980/36981 (TALOS-2024-2004), CVE-2024-39589/39590 (TALOS-2024-2016) — parser fixes present; surface removed | [#11](https://github.com/COG-GTM/OpenPLC_v3/pull/11) | Open, reviewed — `test_enip_default_disabled.py` 3→0, SIL 20/20 |
| F5 | Runtime interactive/command server on 127.0.0.1:43628 accepts `start_*`/`stop_*`/`quit()` with no authentication (`core/interactive_server.cpp`, `openplc.py` `_rpc`) | CWE-306 | AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:H — **7.1** | — | [#9](https://github.com/COG-GTM/OpenPLC_v3/pull/9) | Open, reviewed — `test_interactive_server_token.py` 5→0, SIL 20/20 |
| F6 | Web UI on plaintext HTTP 0.0.0.0:8080; Flask `secret_key = os.urandom(16)` regenerated every start; no cookie hardening (`webserver.py`) | CWE-319, CWE-330, CWE-614 | AV:A/AC:H/PR:N/UI:R/S:U/C:H/I:H/A:N — **6.4** | — | [#4](https://github.com/COG-GTM/OpenPLC_v3/pull/4) | Open, reviewed — `test_session_secret.py` 5→0, SIL 20/20 |
| F7 | `compile-program?file=` passed unvalidated to `open('./st_files/'+st_file)` and `compile_program.sh "$1"`; picture upload keeps client-supplied extension (`webserver.py`, `openplc.py`) | CWE-22, CWE-434 | AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H — **8.8** | — | [#3](https://github.com/COG-GTM/OpenPLC_v3/pull/3) | Open, reviewed — `test_st_filename_traversal.py` 16→0, SIL 20/20 |
| F8 | Settings page runs `hostnamectl set-hostname <web input>` as root with no validation (`webserver.py` `settings()`) | CWE-250, CWE-20 | AV:N/AC:L/PR:L/UI:N/S:C/C:N/I:L/A:L — **6.4** | — | [#7](https://github.com/COG-GTM/OpenPLC_v3/pull/7) | Open, reviewed — `test_hostname_settings.py` + `test_settings_hostname_route.py` 10→0, SIL 20/20 |
| F9 | Dependency pins stale and inconsistent: `requirements.txt` Flask 1.0.2 / Flask-Login 0.4.1; installer pins Werkzeug 2.3.7 (multipart DoS) and leaves several packages unpinned | CWE-1104 | AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H — **7.5** (inherited) | CVE-2023-46136 (Werkzeug) | [#12](https://github.com/COG-GTM/OpenPLC_v3/pull/12) | Open, reviewed — `test_dependency_pins.py` 14→0, SIL 20/20 |
| F10 *(added in triage)* | REST API `/api/delete-user/<id>` and `/api/password-change/<id>` act on any user id for any JWT holder (`restapi.py`) | CWE-862 | AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:L — **7.1** | — | [#2](https://github.com/COG-GTM/OpenPLC_v3/pull/2) | Open, reviewed — `test_restapi_user_authz.py` 3→0, SIL 20/20 |

Notes on triage:

- **F2 is accepted-by-design, mitigated.** The PSM code path is what `talon/L4-WASH-01/hil/` uses, so the remedy is an explicit opt-in setting (default off) plus an audit record, not removal. With the gate off, the shipped controller no longer offers authenticated code execution through the web form.
- **F4 parser CVEs.** The `parseEnipHeader` length check (`enip.cpp`, `buffer_size - 24 < enip_data_size`) that closes CVE-2024-34026 is present in this tree, as are the PCCC fixes; they were verified by code reading, not by a fuzz harness. The PR disables the listener by default, which is the control that actually matters for Line 4.
- **F8 is not shell injection.** `subprocess.run` is used in list form. The defect is unvalidated input reaching a privileged host operation; it is rated and fixed accordingly.
- **F10** was not in the seeded list. `webserver/restapi.py` mounts on the HTTPS port 8443; `delete_user` loads `User.query.get(user_id)` and deletes it after `@jwt_required()` alone. `change_password` requires the target's old password, so it is weaker, but it still lets any token holder act on other accounts. The fix also covers `GET /api/get-user-info/<id>`.
- **F4 was sent back once.** The first revision changed only the shipped `openplc.db` row; `check_openplc_db.py` still seeded `Enip_port=44818` for a database missing the row. The second revision fixes the seed default and adds a test for it.
- **Nothing was non-reproducible.** All ten findings were confirmed by a failing test on the unpatched tree before the fix.

All ten PRs were reviewed for: a test that fails before and passes after, changes limited to the assigned finding, and a green SIL run. All are open against `master` and awaiting human merge. Because the children worked independently from the same base, the PRs overlap and must be landed in order with conflict resolution:

- `talon/security-tests/conftest.py` is added by nine PRs (F5 uses a different layout). Keep one copy; the contents are equivalent (`sys.path` insert of `webserver/`).
- `webserver/openplc.db` (binary) is changed by F1 (hashed `Users` row), F2 (`Psm_editing_enabled=false`) and F4 (`Enip_port=disabled`). Land one, then re-apply the other two as SQL updates to the merged file; the final database must contain all three.
- `webserver/webserver.py` is changed by F1, F2, F6, F7 and F8 in different functions (`login`/user pages, `hardware`/`settings`, app creation, upload/compile, `settings`); F2 and F8 both touch `settings()`.
- `webserver/check_openplc_db.py` is changed by F2 and F4 (adjacent lines).

Suggested order: F10, F3, F5, F9 (no overlap), then F6, F7, F8, F1, F2, F4.

## 3. Residual risk

- **PSM code execution remains available when the operator opts in (F2).** The HIL bench needs it. Anyone who can log in and flip the setting can still run Python as the runtime user. Compensating controls: F1 (no default credential), the audit record, and keeping the setting off on PW-430 in production.
- **Modbus reads stay unauthenticated (F3).** The Ignition gateway polls HR0–7 over plain Modbus; the fix restricts writes and debug function codes to an allow-list, it does not add authentication to the protocol (Modbus has none). A host that is on the allow-list, or that can spoof an allow-listed address on a flat L2 segment, can still write. The `SP_TEMP_X10` plausibility clamp in `L4_WASH_01.st` was *not* added — `talon/L4-WASH-01/` is out of scope for this review — and is recommended as a separate controls-engineering change.
- **The interactive server token is per-boot and local (F5).** It stops unprivileged local processes from stopping the runtime; it does not defend against root on the box. Any local script that drives 127.0.0.1:43628 directly (e.g. `nc`-based bench helpers) must now read `openplc_ctl.token` and prefix each command with it.
- **The legacy UI is still HTTP unless the deployment terminates TLS (F6).** The fix makes the session secret persistent and hardens cookie flags, and makes `Secure` conditional on TLS being present, but does not force HTTPS on 8080 because that would break the current bench and Ignition test flow. See §5.
- **No lockout / rate limiting on the login form.** Not in the seeded list beyond a mention in F1; not fixed. With hashed credentials and no default account it is a lower priority, but it should follow.
- **No role separation in `Users`.** Every account is equivalent. F2's gate and F10's self-service rule reduce what a single account can do, but an RBAC model is a larger change than this review.
- **Werkzeug/Flask were bumped within the 2.x line (F9).** Later majors (Flask 3, pymodbus 3) were deliberately not taken; they change APIs and would be a behaviour change outside a security PR. The separate `neuron` pin set (Flask 2.2.5 / Werkzeug 2.2.2, for which no CVE-2023-46136 fix exists) was folded into the single `requirements.txt`; the Neuron target is not used on Line 4 but should be re-verified if it is ever built.
- **F3 allow-list is opt-in.** If `webserver/mbwrite_allow.list` is absent the runtime logs a warning and keeps the legacy accept-all write behaviour so the bench keeps working; PW-430 must ship the file (see `mbwrite_allow.list.example`) with the Ignition gateway address only.
- **ENIP parser regression tests.** The Talos-shaped fuzz tests that `SECURITY-SWARM.md` §4.4 asks for were not written; the listener is off by default instead. If ENIP is ever re-enabled, those tests should exist first.

## 4. Deliberately out of scope

- The hard-wired safety circuit, the Ignition gateway and the MES (`SECURITY-SWARM.md`, scope statement).
- `talon/L4-WASH-01/` — the ST program, SIL and HIL — was used only as a regression gate; no changes were made there.
- Upstream OpenPLC v4 migration.
- Exploit development or weaponised proofs of concept; all reproductions are tests.
- IT-side controls (EDR on the maintenance laptop, MES/historian hardening) that the peer incidents also implicate.

## 5. Recommended deployment hardening (not code changes)

These are the plant network team's controls that `SECURITY-SWARM.md` §3 assumes and that the code fixes above rely on.

1. **Cell VLAN segmentation.** Keep 172.20.4.0/24 behind the plant firewall with a default-deny policy toward PW-430. Permit only: Ignition gateway → PW-430 tcp/502; the controls-engineering jump host → PW-430 tcp/8080 (or tcp/443 once TLS is terminated). Block 44818, 43628 and everything else at the VLAN boundary regardless of the runtime defaults. Put the maintenance-laptop drop TB-4-430 on a separate VLAN with the same rules, or disable the port when not in use. This is the control that would have prevented the Unitronics campaign.
2. **Modbus write ACL at the network layer.** In addition to the runtime allow-list from F3, enforce on the cell switch/firewall that only the Ignition gateway address may open tcp/502 to PW-430, and, where the firewall supports Modbus DPI, deny function codes 5, 6, 15, 16, 23 and the 0x41–0x45 debug range from any other source. Log every denied write. This is the FrostyGoop control.
3. **HTTPS termination in front of 8080.** Terminate TLS on a reverse proxy or the jump host (plant PKI certificate for `pw-430.l4.kingsport.talon`), forward to 127.0.0.1:8080 only, and set the F6 setting so the session cookie is marked `Secure`. Firewall 8080 from everything except the proxy. Operator credentials then never cross the VLAN in clear.
4. **Credential process.** Rotate the `openplc` account on first commissioning (the F1 PR forces this), issue individual accounts per engineer, and remove accounts when people leave. Record the change in the cell's commissioning log.
5. **Keep PSM editing off on PW-430.** The F2 setting should be enabled only on the HIL bench, never on the production controller; audit the log file at each shutdown.
6. **Monitoring.** Forward the runtime's log and the firewall's denied-write log to the plant SIEM; alert on any tcp/502 write attempt from a non-Ignition source and any login failure burst on 8080.

## 6. Reproduction and verification

- Build: `./install.sh linux` (creates `.venv`; add `pytest` with `.venv/bin/python3 -m pip install pytest`).
- Security tests: `.venv/bin/python3 -m pytest talon/security-tests -q`.
- Regression gate: `cd talon/L4-WASH-01/sil && PATH=$PWD/../../../.venv/bin:$PATH make test` → `20 passed`.

## 7. References

See `talon/SECURITY-SWARM.md` §6 for the incident, advisory and CVE sources. Additional:

- CVE-2023-46136 (Werkzeug multipart resource exhaustion): https://github.com/pallets/werkzeug/security/advisories/GHSA-hrfv-mqp8-q5rw
- CWE definitions: https://cwe.mitre.org/
- CVSS v3.1 specification: https://www.first.org/cvss/v3.1/specification-document
