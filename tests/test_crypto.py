import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pickle_network import client as pn

OPENSSL = shutil.which("openssl")


class CryptoCase(unittest.TestCase):
    def test_pure_python_keygen_and_sealed_bundle(self):
        with mock.patch.object(pn.shutil, "which", return_value=None):
            private_pem = pn.generate_private_pem(1024)
        public_pem = pn.public_pem_from_private(pn.load_private_key(private_pem))
        payload = {"url": "https://mac.example", "token": "pn_12345678_" + "a" * 43,
                   "access": {"client_id": "id.access", "client_secret": "s" * 64}, "note": "긴 값" * 200}
        bundle = pn.seal(payload, public_pem)
        self.assertTrue(bundle.startswith("pn1e."))
        self.assertEqual(pn.open_bundle(bundle, private_pem), payload)
        tampered = bundle[:-4] + ("AAAA" if not bundle.endswith("AAAA") else "BBBB")
        with self.assertRaises(ValueError):
            pn.open_bundle(tampered, private_pem)

    def test_plain_bundle(self):
        payload = {"url": "http://127.0.0.1:1", "token": "t"}
        self.assertEqual(pn.open_bundle(pn.plain_bundle(payload)), payload)

    @unittest.skipUnless(OPENSSL, "openssl 없음")
    def test_oaep_interop_with_openssl(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            key = tmp / "key.pem"
            subprocess.run([OPENSSL, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                            "-out", str(key)], check=True, capture_output=True)
            pub = tmp / "pub.pem"
            subprocess.run([OPENSSL, "pkey", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
            oaep = ["-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256"]
            message = os.urandom(32)
            (tmp / "m").write_bytes(message)
            subprocess.run([OPENSSL, "pkeyutl", "-encrypt", "-pubin", "-inkey", str(pub), "-in", str(tmp / "m"),
                            "-out", str(tmp / "c")] + oaep, check=True, capture_output=True)
            private = pn.load_private_key(key.read_text())
            self.assertEqual(pn.oaep_decrypt(private, (tmp / "c").read_bytes()), message)
            (tmp / "c2").write_bytes(pn.oaep_encrypt(pn.load_public_key(pub.read_text()), message))
            done = subprocess.run([OPENSSL, "pkeyutl", "-decrypt", "-inkey", str(key), "-in", str(tmp / "c2")] + oaep,
                                  check=True, capture_output=True)
            self.assertEqual(done.stdout, message)
            self.assertEqual(pn.public_pem_from_private(private).split(), pub.read_text().split())
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
