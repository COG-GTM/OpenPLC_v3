"""Device hostname setting: validation, persistence and the opt-in OS rename.

The Settings page stores the device hostname in the ``Settings`` table and only
invokes ``hostnamectl set-hostname`` when the operator has explicitly enabled
``Os_hostname_sync``. Every submitted value is validated as an RFC-1123
hostname before it is stored or handed to the operating system.
"""

import socket
import subprocess
from dataclasses import dataclass

from credentials import validate_hostname

HOSTNAME_KEY = 'Device_hostname'
OS_SYNC_KEY = 'Os_hostname_sync'

# Linux HOST_NAME_MAX; hostnamectl rejects anything longer.
OS_HOSTNAME_MAX_LEN = 64


class InvalidHostname(ValueError):
    pass


@dataclass
class HostnameChange:
    hostname: str
    os_changed: bool
    message: str


def validate_device_hostname(hostname):
    if not isinstance(hostname, str) or hostname == '':
        raise InvalidHostname('Hostname must be a non-empty string')
    if hostname != hostname.strip():
        raise InvalidHostname('Hostname must not contain leading or trailing whitespace')
    try:
        return validate_hostname(hostname)
    except ValueError as e:
        raise InvalidHostname(str(e))


def read_hostname_settings(cur):
    cur.execute("SELECT Key, Value FROM Settings WHERE Key IN (?, ?)", (HOSTNAME_KEY, OS_SYNC_KEY))
    values = dict(cur.fetchall())
    stored = values.get(HOSTNAME_KEY) or None
    return stored, values.get(OS_SYNC_KEY) == 'true'


def write_hostname_settings(cur, hostname, os_sync_enabled):
    hostname = validate_device_hostname(hostname)
    cur.execute("INSERT OR REPLACE INTO Settings (Key, Value) VALUES (?, ?)", (HOSTNAME_KEY, hostname))
    cur.execute("INSERT OR REPLACE INTO Settings (Key, Value) VALUES (?, ?)",
                (OS_SYNC_KEY, 'true' if os_sync_enabled else 'false'))


def apply_device_hostname(hostname, os_sync_enabled, current_hostname=None, run=None):
    """Validate ``hostname`` and, only if ``os_sync_enabled``, rename the host.

    Raises ``InvalidHostname`` before anything is executed when the value is
    not a valid hostname. Never calls ``run`` unless the gate is enabled and
    the OS hostname actually differs.
    """
    hostname = validate_device_hostname(hostname)
    if run is None:
        run = subprocess.run

    if not os_sync_enabled:
        return HostnameChange(hostname, False,
                              "Device hostname saved as '" + hostname + "'. The operating system hostname was "
                              "not changed because 'Apply hostname to operating system' is disabled.")

    if len(hostname) > OS_HOSTNAME_MAX_LEN:
        raise InvalidHostname('Hostname too long for the operating system: ' + str(len(hostname)) +
                              ' characters (max ' + str(OS_HOSTNAME_MAX_LEN) + ')')

    if current_hostname is None:
        current_hostname = socket.gethostname()
    if current_hostname == hostname:
        return HostnameChange(hostname, False,
                              "Device hostname saved as '" + hostname + "'. It already matches the operating system hostname.")

    result = run(['hostnamectl', 'set-hostname', hostname])
    if result.returncode != 0:
        return HostnameChange(hostname, False,
                              "Device hostname saved as '" + hostname + "', but hostnamectl failed "
                              "(exit status " + str(result.returncode) + "). The operating system hostname was not changed.")

    return HostnameChange(hostname, True,
                          "Device hostname saved as '" + hostname + "' and applied to the operating system. "
                          "Changes take full effect after a reboot.")
