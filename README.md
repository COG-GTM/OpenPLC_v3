# OpenPLC Runtime version 3

> **⚠️ This project has reached End of Life and is no longer maintained.**
> It has been replaced by [OpenPLC Runtime v4](https://github.com/autonomy-logic/openplc-runtime).
> Please visit the new repository for installation instructions, documentation, and support.

> **Talon Power Systems fork.** This fork carries the Kingsport Engine Plant Line 4 controls
> assets under [`talon/`](talon/README.md): the PW-430 washer program (IEC 61131-3 ST), its
> FDS / IO list / alarm list, a SIL harness and HIL plant model, and the OT security review
> scope. The runtime itself is unmodified upstream OpenPLC v3 (GPLv3).

---

[![Build Status](https://travis-ci.org/thiagoralves/OpenPLC_v3.svg?branch=master)](https://travis-ci.org/thiagoralves/OpenPLC_v3)
[![Build status](https://ci.appveyor.com/api/projects/status/ut3466ixwtyf68qg?svg=true)](https://ci.appveyor.com/project/shrmrf/openplc-v3)

OpenPLC is an open-source [Programmable Logic Controller](https://en.wikipedia.org/wiki/Programmable_logic_controller) that is based on easy to use software. Our focus is to provide a low cost industrial solution for automation and research. OpenPLC has been used in [many research papers](https://scholar.google.com/scholar?as_ylo=2014&q=openplc&hl=en&as_sdt=0,1) as a framework for industrial cyber security research, given that it is the only controller to provide the entire source code.
The OpenPLC Project consists of two sub-projects:
1. [Runtime](https://github.com/thiagoralves/OpenPLC_v3)
2. [Programming editor](https://openplcproject.com/docs/installing-openplc-editor/)


## Installation:
```bash
git clone https://github.com/COG-GTM/OpenPLC_v3.git
cd OpenPLC_v3
./install.sh [platform]
```

The install builds the toolchain and runtime from source and takes about 15 minutes. It needs `git` and `sudo` (it calls `sudo apt-get`, `yum` or `zypper` itself; on Fedora-based hosts the `yum` command must exist, a `dnf`-only host is rejected as unsupported).

Where `[platform]` can be:

`win` - Install OpenPLC on Windows over Cygwin

`linux` - Install OpenPLC on a supported Linux distribution, currently Debian-based, Fedora-based, Opensuse and Alpine Linux is supported.

`docker` - Used by the `Dockerfile` (i.e. doesn't invoke `sudo`)

`rpi` - Install OpenPLC on a Raspberry Pi

`custom` - Skip all specific package installation and tries to install OpenPLC assuming your system already has all dependencies met. This option can be useful if you're trying to install OpenPLC on an unsuported Linux platform or had manually installed all the dependency packages before.

### Running
On `linux`, `rpi` and `custom`, the installer registers an `openplc` systemd service that starts on boot. On a systemd host, run `sudo systemctl start openplc` to start it right away. On any host (including ones without systemd, where the service step fails but the install still finishes) you can run the runtime in the foreground instead. Stop the service first (`sudo systemctl stop openplc`) if it is running, since both use the same ports:

```bash
sudo ./start_openplc.sh
```

`sudo` is needed because the Modbus server listens on port 502. On `win` (Cygwin), run `./start_openplc.sh` without `sudo`. Open http://localhost:8080 and sign in with the default user `openplc`, password `openplc`. The web UI (port 8080) and the REST API (HTTPS port 8443) listen on all network interfaces, so change the password under Users right after the first sign-in, before the host is reachable from other machines. The REST API keeps its own accounts and lets anyone create the first one, so also create that first account or block port 8443 before exposing the host:

```bash
curl -k -X POST https://localhost:8443/api/create-user -H 'Content-Type: application/json' -d '{"username": "<user>", "password": "<password>"}'
```

The runtime starts in the Stopped state: click Start PLC on the Dashboard to run the loaded program, or enable "Start OpenPLC in RUN mode" under Settings to have it start on boot.

The `custom` platform skips package installation, so the `openssl` command must already be installed (the REST API uses it to create its TLS certificate). It also needs Python 3.10 or newer, and it skips Python setup, but both start options run `.venv/bin/python3`. Before starting, create the virtualenv yourself:

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install flask==2.3.3 werkzeug==2.3.7 flask-login==0.6.2 pyserial pymodbus==2.5.3 flask_jwt_extended flask_sqlalchemy python-dotenv
```

### Building, Installing and Running inside Docker
When using Ubuntu: make sure [`docker for Ubuntu` is installed](https://docs.docker.com/install/linux/docker-ce/ubuntu/)

When using Linux Mint 21: make sure [`docker for Linux Mint 21` is installed](https://computingforgeeks.com/install-docker-docker-compose-on-linux-mint/)

#### Build
```
# instead of running install.sh as stated above, run:
docker build -t openplc:v3 .
```

#### RUN
_Devices can be passed to the `docker` daemon using the `-v` flag (e.g. `-v /dev/ttyACM0:/dev/ttyACM0`)_

```bash
docker run -it --rm --privileged -p 8080:8080 openplc:v3
```

Then open http://localhost:8080, sign in with `openplc` / `openplc` (or the password you set, when reusing a volume) and click Start PLC (see [Running](#running) about changing the password). To keep the web UI database (users, settings, program list) and uploaded `.st` files between runs, add `-v openplc-data:/docker_persistent`. Two things are not kept in the volume. First, the compiled program: a new container runs the image's blank program until you open the program under Programs and click Launch program to recompile it. Second, the REST API's accounts and secrets (its SQLite database and `.env`, both outside `/docker_persistent`), which start fresh in each new container.

### EtherCAT capability
To build with EtherCAT capability try `./install.sh linux ethercat` for more information see `utils/ethercat_src`
