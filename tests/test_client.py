import unittest
from pathlib import Path

from pickle_network import client as pn


class ClientPathCase(unittest.TestCase):
    def test_shell_expanded_home_returns_to_tilde(self):
        home = str(Path.home())
        self.assertEqual(pn.mac_path(home + "/work/a.txt"), "~/work/a.txt")
        self.assertEqual(pn.mac_path(home), "~")
        self.assertEqual(pn.mac_path("~/x"), "~/x")
        self.assertEqual(pn.mac_path("/opt/data"), "/opt/data")
        self.assertEqual(pn.mac_path(home + "other/x"), home + "other/x")
        self.assertIsNone(pn.mac_path(None))


if __name__ == "__main__":
    unittest.main()
