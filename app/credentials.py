import logging
import os
import subprocess

log = logging.getLogger(__name__)


def load_credentials():
    email = os.getenv("ANAPLAN_EMAIL", "").strip()
    password = os.getenv("ANAPLAN_PASSWORD", "")
    service = os.getenv("ANAPLAN_KEYCHAIN_SERVICE", "").strip()
    if password or not (email and service):
        return email, password
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", email, "-w"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        password = result.stdout.rstrip("\r\n")
        if password:
            log.info("Loaded Anaplan password from macOS Keychain service %r.", service)
    except (FileNotFoundError, subprocess.SubprocessError):
        log.warning("Could not load the Anaplan password from macOS Keychain service %r.", service)
    return email, password
