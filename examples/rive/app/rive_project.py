"""A project registration hook; the SDK route/registry files stay unchanged."""

from rive_activity import register_rive_activity


def setup(api):
    register_rive_activity(api)
