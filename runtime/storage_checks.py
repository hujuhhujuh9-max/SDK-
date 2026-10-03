"""Validate the runner's durable storage and selected native files."""

import hashlib
import json
import os
import re
from pathlib import Path


PERSISTENCE_KEY = "sdk.runner.validation.persistence"
RECEIPT_NAME = "runner-storage-probe.json"


async def check_persistence(preferences, secure, directory):
    """Read any earlier challenge before writing; never repair missing evidence."""
    directory = Path(directory)
    receipt_path = directory / RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    preference_value = await preferences.get(PERSISTENCE_KEY)
    secure_value = await secure.get(PERSISTENCE_KEY)
    state = "restored"
    if receipt is None:
        if preference_value is not None or secure_value is not None:
            raise RuntimeError("Durable storage receipt is missing for an existing challenge")
        state = "seeded"
        receipt = {"token": os.urandom(32).hex(), "source_pid": os.getpid()}
        token = receipt["token"]
        if not await preferences.set(PERSISTENCE_KEY, token):
            raise RuntimeError("Shared preferences refused the durability challenge")
        await secure.set(PERSISTENCE_KEY, token)
        if await preferences.get(PERSISTENCE_KEY) != token or await secure.get(PERSISTENCE_KEY) != token:
            raise RuntimeError("Durability challenge readback failed")
        directory.mkdir(parents=True, exist_ok=True)
        pending = receipt_path.with_suffix(".tmp")
        try:
            with pending.open("w", encoding="utf-8") as stream:
                json.dump(receipt, stream)
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(receipt_path)
        finally:
            pending.unlink(missing_ok=True)
    else:
        if not isinstance(receipt, dict):
            raise RuntimeError("Invalid durable storage receipt")
        token = receipt.get("token")
        if (not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None
                or type(receipt.get("source_pid")) is not int or receipt["source_pid"] <= 0):
            raise RuntimeError("Invalid durable storage receipt")
        if preference_value != token or secure_value != token:
            raise RuntimeError("Stored file, preferences and secure storage disagree")
    return {"state": state, "pid": os.getpid(), "source_pid": receipt["source_pid"],
            "sha256": hashlib.sha256(receipt["token"].encode("ascii")).hexdigest()}


def picked_file_receipt(selected):
    """Hash in bounded chunks; Android's picker supplies an app-readable cached path."""
    if not selected.path:
        raise RuntimeError("Selected file has no native readable path")
    digest = hashlib.sha256()
    size = 0
    with Path(selected.path).open("rb") as stream:
        for block in iter(lambda: stream.read(64 * 1024), b""):
            size += len(block)
            digest.update(block)
    if size != selected.size:
        raise RuntimeError("Selected file size differs from its native picker metadata")
    return {"name": selected.name, "size": size, "sha256": digest.hexdigest()}
