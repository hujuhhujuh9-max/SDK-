"""Socket framing shared by the runner's Flet integration checks."""

import time


def receive_exact(client, count):
    data = bytearray()
    while len(data) < count:
        chunk = client.recv(count - len(data))
        if not chunk:
            raise RuntimeError("Flet closed its protocol connection")
        data.extend(chunk)
    return bytes(data)


def connect(client, path, seconds=15):
    # A previous server can leave its socket filename while the next bind is
    # still starting. Existence alone does not establish a live listener.
    deadline = time.monotonic() + seconds
    while True:
        try:
            client.connect(str(path))
            return
        except (FileNotFoundError, ConnectionRefusedError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def receive(client, codec, max_size=16 * 1024 * 1024):
    size = int.from_bytes(receive_exact(client, 4), "little")
    assert 0 < size <= max_size, size
    packet = receive_exact(client, size)
    assert packet[0] == 0
    message = codec.unpackb(packet[1:], strict_map_key=False)
    assert message[0] != 6, ("Flet session crashed", message)
    return message


def send(client, codec, action, body):
    packet = b"\x00" + codec.packb([action, body])
    client.sendall(len(packet).to_bytes(4, "little") + packet)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)


def until(client, codec, predicate):
    for _ in range(100):
        message = receive(client, codec)
        if predicate(message):
            return message
    raise AssertionError("Expected UI patch was not received")
