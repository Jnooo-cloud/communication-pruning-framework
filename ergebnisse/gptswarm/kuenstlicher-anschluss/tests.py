"""Run existing and Z31 tests with an actual socket-connect guard."""
import sys

def deny_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("Z31 prohibits network calls during tests")

sys.addaudithook(deny_network)
import unittest
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
raise SystemExit(0 if result.wasSuccessful() else 1)
