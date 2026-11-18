import base64
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pickle_network import client as pn
from pickle_network.devices import Devices
from pickle_network.paths import default_config, ensure_home, write_json


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pn-test-")).resolve()
        os.environ["PICKLE_NETWORK_HOME"] = str(self.tmp / "home")
        self.root = ensure_home()
        self.work = self.tmp / "work"
        self.work.mkdir()
        fake = self.tmp / "fakebin"
        fake.mkdir()
        script = fake / "claude"
        script.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then echo 9.9.9; exit 0; fi\n"
                          "printf 'ARGS:'; for a in \"$@\"; do printf '[%s]' \"$a\"; done; echo\n")
        script.chmod(0o755)
        write_json(self.root / "env.json", {"path": "%s:/usr/bin:/bin" % fake, "source": "test"})
        config = default_config()
        config.update({"roots": [str(self.tmp)], "default_cwd": str(self.work), "concurrency": 2})
        from pickle_network.server import App, Server
        self.app = App(self.root, config)
        self.server = Server(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()
        devices = Devices(self.root / "devices.json")
        _, self.token = devices.create("tester")
        _, self.read_token = devices.create("viewer", "read")
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        self.client = pn.Client({"url": self.url, "token": self.token})

    def tearDown(self):
        self.server.shutdown()
        self.app.jobs.shutdown()
        self.server.server_close()
        self.app.jobs.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("PICKLE_NETWORK_HOME", None)

    def call(self, method, path, body=None, query=None, token=None):
        c = self.client if token is None else pn.Client({"url": self.url, "token": token})
        return c.request(method, path, body=body, query=query, timeout=30)

    def test_hello_and_auth_layers(self):
        status, value = self.call("GET", "/v1/hello")
        self.assertEqual(status, 200)
        self.assertEqual(value["agents"], {"claude": "9.9.9"})
        status, value = self.call("GET", "/v1/hello", token="pn_00000000_" + "a" * 43)
        self.assertEqual((status, value["error"]["code"]), (401, "unauthorized"))
        conn = self.client._connection(5)
        conn.request("GET", "/v1/hello", headers={"Authorization": "Bearer " + self.token, "Origin": "https://x"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()

    def test_run_wait_and_idempotency(self):
        body = {"command": "echo hello; echo oops >&2; exit 3", "wait": 20, "request_id": "same-1"}
        status, value = self.call("POST", "/v1/run", body)
        self.assertEqual(status, 202)
        job = value["job"]
        self.assertEqual((job["state"], job["exit_code"]), ("failed", 3))
        self.assertEqual(job["stdout"], "hello\n")
        self.assertEqual(job["stderr"], "oops\n")
        self.assertEqual(job["cwd"], str(self.work))
        status, again = self.call("POST", "/v1/run", body)
        self.assertEqual((status, again["reused"], again["job"]["id"]), (200, True, job["id"]))
        status, conflict = self.call("POST", "/v1/run", dict(body, command="echo other"))
        self.assertEqual((status, conflict["error"]["code"]), (409, "request_id_conflict"))

    def test_live_output_and_cancel(self):
        status, value = self.call("POST", "/v1/run", {"command": "for i in 1 2 3 4 5 6 7 8 9; do echo line$i; sleep 0.3; done; sleep 30"})
        job_id = value["job"]["id"]
        time.sleep(1.2)
        status, out = self.call("GET", "/v1/jobs/%s/output" % job_id, query={"offset": 0})
        self.assertIn("line1", out["output"]["text"])
        self.assertFalse(out["output"]["eof"])
        offset = out["output"]["next_offset"]
        time.sleep(0.8)
        status, more = self.call("GET", "/v1/jobs/%s/output" % job_id, query={"offset": offset})
        self.assertTrue(more["output"]["text"].startswith("line"))
        self.assertNotIn("line1\n", more["output"]["text"])
        status, canceled = self.call("POST", "/v1/jobs/%s/cancel" % job_id, {})
        self.assertEqual(status, 202)
        status, final = self.call("GET", "/v1/jobs/" + job_id, query={"wait": 15})
        self.assertEqual(final["job"]["state"], "canceled")

    def test_concurrent_jobs_and_timeout(self):
        started = time.monotonic()
        _, slow = self.call("POST", "/v1/run", {"command": "sleep 3", "timeout": 1})
        _, fast = self.call("POST", "/v1/run", {"command": "echo quick", "wait": 10})
        self.assertEqual(fast["job"]["state"], "succeeded")
        self.assertLess(time.monotonic() - started, 2.5)
        _, final = self.call("GET", "/v1/jobs/" + slow["job"]["id"], query={"wait": 10})
        self.assertEqual(final["job"]["state"], "timed_out")

    def test_ask_builds_agent_command(self):
        _, value = self.call("POST", "/v1/ask", {"prompt": "고쳐 줘", "agent": "claude", "mode": "edit",
                                                 "model": "sonnet", "wait": 20})
        self.assertEqual(value["job"]["state"], "succeeded")
        self.assertIn("[-p][고쳐 줘]", value["job"]["stdout"])
        self.assertIn("[--permission-mode][acceptEdits][--model][sonnet]", value["job"]["stdout"])
        status, value = self.call("POST", "/v1/ask", {"prompt": "x", "agent": "gemini"})
        self.assertEqual((status, value["error"]["code"]), (404, "agent_missing"))
        status, value = self.call("POST", "/v1/ask", {"prompt": "x", "model": "--evil"})
        self.assertEqual(status, 400)

    def test_files_roundtrip_and_roots(self):
        target = str(self.work / "deep" / "note.txt")
        status, value = self.call("PUT", "/v1/files", {"path": target, "content": "안녕", "create_dirs": True})
        self.assertEqual(status, 200)
        digest = value["written"]["sha256"]
        _, value = self.call("GET", "/v1/files", query={"path": target})
        self.assertEqual(value["file"]["content"], "안녕")
        status, value = self.call("PUT", "/v1/files", {"path": target, "content": "x", "expected_sha256": "0" * 64})
        self.assertEqual((status, value["error"]["code"]), (409, "sha256_mismatch"))
        status, _ = self.call("PUT", "/v1/files", {"path": target, "content": "x", "expected_sha256": digest})
        self.assertEqual(status, 200)
        binary = base64.b64encode(b"\x00\xff\x10").decode()
        self.call("PUT", "/v1/files", {"path": str(self.work / "b.bin"), "content_base64": binary})
        _, value = self.call("GET", "/v1/files", query={"path": str(self.work / "b.bin")})
        self.assertEqual((value["file"]["encoding"], value["file"]["content"]), ("base64", binary))
        _, value = self.call("GET", "/v1/files", query={"path": str(self.work)})
        self.assertEqual([e["name"] for e in value["dir"]["entries"]], ["deep", "b.bin"])
        status, value = self.call("GET", "/v1/files", query={"path": "/etc/hosts"})
        self.assertEqual((status, value["error"]["code"]), (403, "path_denied"))
        link = self.work / "escape"
        link.symlink_to("/etc")
        status, _ = self.call("GET", "/v1/files", query={"path": str(link / "hosts")})
        self.assertEqual(status, 403)

    def test_read_only_device(self):
        status, value = self.call("POST", "/v1/run", {"command": "true"}, token=self.read_token)
        self.assertEqual((status, value["error"]["code"]), (403, "scope_denied"))
        status, _ = self.call("GET", "/v1/jobs", token=self.read_token)
        self.assertEqual(status, 200)

    def test_rejects_unknown_fields_and_bad_cwd(self):
        status, value = self.call("POST", "/v1/run", {"command": "true", "shell": "bash"})
        self.assertEqual((status, value["error"]["code"]), (400, "invalid_field"))
        status, value = self.call("POST", "/v1/run", {"command": "true", "cwd": "/nope/nowhere"})
        self.assertEqual((status, value["error"]["code"]), (400, "invalid_cwd"))

    def test_restart_marks_running_jobs_interrupted(self):
        from pickle_network.jobs import Jobs
        _, value = self.call("POST", "/v1/run", {"command": "true", "wait": 10})
        db = self.app.jobs.db
        db.execute("UPDATE jobs SET state='running', pid=4242")
        db.commit()
        jobs = Jobs(self.root, self.app.config, dict)
        job = jobs.get(value["job"]["id"])
        jobs.shutdown()
        jobs.db.close()
        self.assertEqual(job["state"], "interrupted")
        self.assertEqual(job["error"]["code"], "server_restarted")


if __name__ == "__main__":
    unittest.main()
