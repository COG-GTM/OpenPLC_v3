# OT Security Review — OpenPLC Runtime as deployed on Line 4 (PW-430)

**Talon Power Systems — Kingsport Engine Plant — Controls Engineering / OT Security**
Review scope: the OpenPLC Runtime v3 fork in this repository, as installed on the Cell 4-30 washer controller (`webserver/`, `webserver/core/`), plus the Line 4 network position described in section 3. Out of scope: the hard-wired safety circuit, the Ignition gateway, the MES.

## 1. Why we are looking at this now

Kingsport runs one OpenPLC controller in production (PW-430, since the 2019 heater retrofit) and four more on the Line 4 pilot cells, all on the same Runtime v3 code line. Upstream declared Runtime v3 end-of-life and moved to v4; we own the code we are running. The corporate cyber risk committee asked each plant to document the exposure of any controller that is not covered by a vendor support contract, citing the following incidents (all public, all verifiable):

| When | Who | What happened | Why it is relevant to a plant like ours |
|---|---|---|---|
| Nov 2023 | US water utilities and other sectors (CISA AA23-335A) | IRGC-affiliated "CyberAv3ngers" defaced and disabled internet-reachable Unitronics Vision PLCs/HMIs that still had the default password; victims spanned multiple US states and sectors including food & beverage manufacturing. | A PLC web interface with a default credential, reachable from the wrong network segment, is the whole attack. This runtime ships with `openplc`/`openplc`. |
| Jan 2024 (reported Jul 2024) | District heating operator, Lviv (Dragos: FrostyGoop) | ICS malware wrote directly to controllers over Modbus/TCP (port 502) exposed to the internet; ~600 buildings lost heat for two days in sub-zero weather. | Our setpoints (`%MW0..5`) and HMI registers are plain Modbus holding registers. Modbus has no authentication by design; anything that can reach port 502 can change the wash temperature. |
| Aug 2023 | The Clorox Company (8-K, Oct 2023) | Cyberattack caused wide-scale operational disruption, order-processing delays and product outages; Q1 FY24 net sales guided down 23–28 %. | IT-side compromise stopped plants. Our MES/historian link is the same kind of IT/OT seam. |
| Sep 2023 | Johnson Controls (8-K, Jan 2024) | Ransomware; $27 M remediation cost, data exfiltrated. | A building-automation and controls vendor was itself the victim. |
| Aug 2024 | Halliburton (8-K, Aug 2024) | Unauthorized access; systems taken offline proactively; ~$35 M expenses reported by November. | Industrial services; "take systems offline" is what our plant would have to do. |
| Apr 2025 | Sensata Technologies (8-K, Apr 2025) | Ransomware encrypted devices; shipping, receiving and manufacturing production impacted; files exfiltrated. | A sensor/controls manufacturer, i.e. one of our own suppliers' peers. |
| May 2025 | Nucor (8-K, May 2025) | Unauthorized access to IT systems; production halted at multiple locations as a precaution. | A US steelmaker stopped melting because of an IT incident. |
| Sep 2025 | Jaguar Land Rover (Reuters/BBC) | Cyberattack halted vehicle production for weeks; UK government backed a £1.5 bn ($2 bn) loan guarantee for the supplier base. | An OEM outage that propagated into hundreds of Tier 1/2 suppliers — including engine-plant peers. |

Vendor guidance in the same period says the same thing from the other side: Rockwell Automation (SD1672, May 2024) told all customers to immediately disconnect any ICS device from the public internet; Schneider Electric (SEVD-2024-317-03) published Modbus-based memory-tampering CVEs on Modicon M340 controllers that read almost identically to the exposure in section 4.3.

## 2. What is known about this codebase specifically

OpenPLC Runtime v3 has a public vulnerability record. Where the fix is already in this tree it is noted; the review should still confirm each by reading the code and, where practical, by writing a regression test.

| CVE / advisory | Component | Nature | Status in this fork |
|---|---|---|---|
| CVE-2021-31630 | `webserver.py` `/hardware` "Hardware Layer Code Box" | Authenticated remote code execution: the text area is written verbatim to `core/psm/main.py` and executed by the runtime as root. CVSS 8.8. | **Present by design.** This is the PSM feature that `talon/L4-WASH-01/hil/` relies on. Mitigation is access control and network position, not removal. |
| CVE-2024-34026 (TALOS-2024-2005) | `core/enip.cpp` unknown-command logging | Stack-based buffer overflow in the EtherNet/IP parser → RCE from a single unauthenticated packet on 44818. | Fixed upstream (`d5d475c`, `df16a98`); fix is in this tree. No regression test exists. |
| CVE-2024-36980 / CVE-2024-36981 (TALOS-2024-2004) | `core/enip.cpp` PCCC parser | Out-of-bounds reads. | Fixed upstream (`df16a98`); no regression test. |
| CVE-2024-39589 / CVE-2024-39590 (TALOS-2024-2016) | `core/enip.cpp` PCCC Protected Logical Read/Write reply | Invalid pointer dereference (truncated 64-bit pointer) → crash / DoS. | Fixed upstream (`df16a98`); no regression test. |

## 3. Network position of PW-430

```
  Corporate IT ── firewall ── Plant DMZ (Ignition gateway, historian)
                                   │  Modbus/TCP 502 (Ignition → PLC, 1 s poll, read HR0-7, write HR1024-1029)
                            L4 cell VLAN 172.20.4.0/24
                                   ├── PW-430 controller  (OpenPLC: 8080 web, 502 Modbus, 44818 ENIP*, 43628 interactive†)
                                   ├── VFD-1, remote I/O drop (Modbus/TCP 172.20.4.31/.32)
                                   └── maintenance laptop drop (TB-4-430, live)
```
\* ENIP is on by default in `openplc.db` (`Enip_port = 44818`) and was never disabled after the 2022 Kepware trial. † Loopback only, unauthenticated.

## 4. Findings to confirm and remediate (starting list for the swarm)

Each item states what the code does today; the swarm confirms, rates, and fixes. Fixes must not change `%I/%Q/%M` behaviour of the running program — `talon/L4-WASH-01/sil` must still pass.

1. **Default and plaintext credentials.** `openplc.db` ships user `openplc` / password `openplc`; `webserver.py` stores and compares passwords in cleartext (`row[1] == password`), and the user-edit form echoes a sentinel `mypasswordishere`. No lockout, no rate limit. (Cf. Unitronics.)
2. **Hardware-layer code box = RCE for any authenticated user.** Any account, not only an admin, can write `core/psm/main.py` and restart the runtime. There is no role separation in the Users table. Decide: role gate + audit log, or make the feature build-time optional.
3. **Unauthenticated Modbus writes to setpoints.** HR1024–1029 (`%MW0..5`) accept writes from any client on 502. FrostyGoop-class impact: raise `SP_TEMP_X10` to 950, drop `SP_JAM_TIME_S` to 1. Options in scope for the runtime: source-IP allow-list in `modbus.cpp`, read-only register ranges, or plausibility clamps at the point of use in `L4_WASH_01.st` (defence in depth — the ST clamps hysteresis already; it does not clamp temperature).
4. **ENIP/PCCC server enabled with no consumer.** Attack surface with a CVE history and no regression tests; should default off and be covered by a fuzz-shaped test using the Talos PoC shapes.
5. **Interactive server (43628) has no authentication.** It binds loopback, which is right, but any local process — including Python injected through finding 2 — can issue `start_modbus()`, `stop_*`, `quit()`. Chain with 1+2 and rate accordingly; consider a per-boot token shared with `webserver.py`.
6. **Web UI over HTTP on 8080, session secret regenerated per start.** Credentials cross the cell VLAN in clear; the maintenance laptop drop is live.
7. **Upload paths.** `/upload-program` renames the `.st` to `random.randint(1,1000000).st` (no traversal, but collision-prone and not cryptographically random); compilation shells out via `scripts/compile_program.sh <name>` with the DB-stored name. User picture uploads (`/add-user`, `/update-user`) keep the client-supplied extension with no allow-list and serve it from `/static/`. Confirm both.
8. **`settings` → `hostnamectl set-hostname`** with a user-supplied value via `subprocess.run` (list form, so no shell injection) — but it runs as root from a web form. Low, document.
9. **Dependencies.** `requirements.txt` pins Flask/Werkzeug/pymodbus versions from the 2019–2023 era; run the SCA and patch what is not breaking.

## 5. Remediation workflow (how the swarm should work)

1. **Triage, one branch per finding.** Branch `devin/<ts>-sec-<n>-<slug>`; commit messages carry `feature` or `bug` per repo convention. One finding per PR so the controls engineer can review each on its own.
2. **Prove before fixing.** Add a failing test or reproducible script under `webserver/tests/` (Flask test client for web findings; `pymodbus` client for Modbus findings; raw-socket packet for ENIP) that demonstrates the issue against the unpatched code.
3. **Fix inside the runtime, not around it.** No new services, no reverse proxies, no "put it behind a firewall" as the only remedy — those are the plant network team's controls and are already assumed in section 3.
4. **Regression: the PLC program must not notice.** Run `make -C talon/L4-WASH-01/sil test` (20 SIL tests) and compile `L4_WASH_01.st` through `scripts/compile_program.sh`. A security fix that changes scan behaviour is a defect.
5. **PR body.** Finding number from section 4, CVE/CWE reference, what was exploitable and from where (section 3 vantage point), what changed, how it was tested, and any operational impact (e.g. "Modbus writes now rejected from outside 172.20.4.0/24 — Ignition gateway allow-listed"). End with the org tag required by the repo.
6. **Severity language.** Use CVSS v3.1 vectors, not adjectives. Anything reachable from the cell VLAN without authentication that can change a setpoint or stop the runtime is Critical for this site regardless of the generic CVSS.

## 6. References

- CISA AA23-335A — IRGC-affiliated cyber actors exploit PLCs (Unitronics): https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-335a
- Dragos, "Impact of FrostyGoop ICS malware" (Jul 2024): https://hub.dragos.com/hubfs/Reports/Dragos-FrostyGoop-ICS-Malware-Intel-Brief-0724_r2.pdf
- Clorox preliminary Q1 FY24 results (Oct 4 2023): https://www.sec.gov/Archives/edgar/data/21076/000120677423001174/clx4249171-ex991.htm
- Johnson Controls ransomware cost (Dark Reading, Jan 2024): https://www.darkreading.com/ics-ot-security/johnson-controls-ransomware-cleanup-costs-27m
- Halliburton 8-K (Aug 21 2024): https://www.sec.gov/Archives/edgar/data/45012/000004501224000049/hal-20240821.htm ; cost: https://www.cybersecuritydive.com/news/halliburton-35-million-cyberattack/732397/
- Sensata Technologies 8-K (Apr 6 2025): https://www.sec.gov/Archives/edgar/data/1477294/000147729425000047/st-20250406.htm
- Nucor 8-K Item 1.05 (May 2025): https://www.sec.gov/Archives/edgar/data/73309/000119312525119311/0001193125-25-119311-index.htm
- JLR phased restart (Reuters, Sep 29 2025): https://www.reuters.com/en/tata-motors-jlr-return-manufacturing-after-cyber-attack-2025-09-29/
- Rockwell Automation SD1672 (May 2024): https://www.rockwellautomation.com/en-se/trust-center/security-advisories/advisory.SD1672.html
- Schneider Electric SEVD-2024-317-03 (Modicon M340): https://download.se.com/doc/SEVD-2024-317-03/SEVD-2024-317-03.pdf
- CVE-2021-31630: https://www.cve.org/CVERecord?id=CVE-2021-31630
- TALOS-2024-2005 (CVE-2024-34026): https://www.talosintelligence.com/vulnerability_reports/TALOS-2024-2005
- TALOS-2024-2004 (CVE-2024-36980/36981): https://www.talosintelligence.com/vulnerability_reports/TALOS-2024-2004
- TALOS-2024-2016 (CVE-2024-39589/39590): https://talosintelligence.com/vulnerability_reports/TALOS-2024-2016
