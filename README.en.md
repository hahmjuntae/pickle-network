# Pickle Network

[한국어](README.md) | **English**

Ask Pickle. Your Mac does the work.

---

## 1. Overview

### 1.1 Purpose

This document gives the procedure to install Pickle Network and connect it to Pickle.

### 1.2 Scope

With Pickle Network, Pickle can do these tasks on your Mac:

| Task | Example |
|---|---|
| Run terminal commands | Tests, builds, file cleanup |
| Read and write files | Read documents, save notes |
| Send tasks to AI tools | Claude Code, Codex, Gemini CLI, AGY |
| Manage jobs | Monitor progress, read output, cancel |

### 1.3 System Diagram

```
  Pickle                      Cloudflare                  My Mac
 ┌────────────┐   HTTPS    ┌────────────┐            ┌──────────────────┐
 │  pn.py     │ ─────────▶ │  Tunnel    │ ─────────▶ │  pickle-network  │
 └────────────┘            └────────────┘            └────────┬─────────┘
                                                              │
                                    ┌─────────────┬───────────┼─────────────┐
                                    ▼             ▼           ▼             ▼
                                 terminal       files      AI CLIs      job log
                                  (zsh)                  claude, codex  (SQLite)
                                                         gemini, agy
```

---

## 2. Quick Start Prompt

Paste this text into an AI coding tool (Claude Code, Codex, or equivalent). The AI tool does [4. Installation](#4-installation).

```
Clone https://github.com/hahmjuntae/pickle-network into ~/pickle-network and install it as the README says. Then show me the output of pickle-network doctor and the message that pickle-network pair prints.
```

Send the message from the AI tool to Pickle. Then do step 5.2 in [5. Pairing](#5-pairing).

---

## 3. Requirements

| Item | Condition | Check command |
|---|---|---|
| macOS | User is logged in | `sw_vers` |
| Python | 3.9 or later (included in macOS) | `python3 --version` |
| Git | Any version | `git --version` |
| Homebrew | Any version | `brew --version` |
| Pickle | An account that can chat | Pickle app |

You do not need a Cloudflare account or a domain.

---

## 4. Installation

Run these commands in Terminal, in this sequence.

### 4.1 Install cloudflared

```bash
brew install cloudflared
```

### 4.2 Download

```bash
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
```

### 4.3 Set Up the Server

```bash
~/pickle-network/bin/pickle-network setup
```

### 4.4 Open the Tunnel

```bash
~/pickle-network/bin/pickle-network tunnel quick
```

The server and the tunnel start automatically when the Mac starts.

---

## 5. Pairing

### 5.1 Request a Key

1. Run this command:

   ```bash
   pickle-network pair
   ```

2. Send the printed message to Pickle.
3. Wait for Pickle to send a public key (`-----BEGIN PUBLIC KEY-----`).

### 5.2 Create the Connection Message

1. Copy the full public key from Pickle.
2. Run this command:

   ```bash
   pbpaste > ~/pickle.pub && pickle-network pair --key ~/pickle.pub --copy
   ```

### 5.3 Send the Connection Message

1. Send the message on the clipboard to Pickle.
2. When Pickle sends the Mac name and the list of AI tools, the connection is complete.

---

## 6. Verification

```bash
pickle-network doctor
```

All lines must show `[OK  ]`. If a line shows `[FAIL]`, refer to [10. Troubleshooting](#10-troubleshooting).

The command output is in Korean.

---

## 7. Usage

### 7.1 Example Prompts

Write to Pickle in normal sentences.

```
Run the tests in ~/projects/blog on my Mac. If they fail, fix them with Claude Code and tell me the result.
```

```
On my Mac, list the PDF files in ~/Downloads from this week, largest first.
```

```
Is the job from before still running? Show me the output so far.
```

### 7.2 Reset Prompt

If Pickle does not obey the usage rules, send this text:

```
Run python3 pn.py guide, read the pickle-network usage rules again, and obey them.
```

### 7.3 Commands

| Command | Function |
|---|---|
| `pickle-network status` | Show the status and the public address |
| `pickle-network doctor` | Test the connection |
| `pickle-network pair` | Make a connection message |
| `pickle-network pair --replace --copy` | Make a new connection message after the address changes |
| `pickle-network devices` | Show the connected assistants |
| `pickle-network devices revoke pickle` | Disconnect an assistant |
| `pickle-network stop` | Stop the server and the tunnel |
| `pickle-network start` | Start the server and the tunnel |
| `pickle-network logs` | Show the server log |

---

## 8. Architecture

### 8.1 Request Flow

```
 Pickle                         pickle-network (127.0.0.1)
 ──────                         ──────────────────────────
 POST /v1/ask  ──────────────▶  1. check device token        → 401 if wrong
                                2. put job in queue          → up to 3 at once
                                3. run CLI in new process    → output saved live
 ◀─── result (wait ≤ 90s) ───   4. return exit code + output
 GET /v1/jobs/{id}  ─────────▶  5. still running? keep waiting or cancel
```

1. The server accepts requests only on `127.0.0.1`.
2. External requests come in only through Cloudflare Tunnel.
3. The server checks the device token for each request.
4. The server keeps only a hash of each token.
5. The server runs a maximum of 3 jobs at the same time.
6. The server writes the output to a file while the job runs.
7. Pickle waits a maximum of 90 seconds for a result. For a longer job, Pickle waits again with the job ID or cancels the job.

### 8.2 Pairing Sequence

```
  My Mac                                        Pickle
  ──────                                        ──────
  pickle-network pair
        │ ─────── 1. key request ───────────▶  python3 pn.py keygen
        │ ◀────── 2. public key ────────────
  pickle-network pair --key pickle.pub
        │ ─────── 3. connect message ───────▶  python3 pn.py connect 'pn1e...'
        │                                      python3 pn.py hello
        │ ◀────── 4. "connected" ───────────
```

The connection message contains the Mac address and a device token. The public key of Pickle encrypts the connection message. Only the private key of Pickle can open it.

### 8.3 Directory Layout

```
~/pickle-network/               Repository
├── bin/pickle-network          Mac command
├── pickle_network/
│   ├── server.py               HTTP server, authentication
│   ├── jobs.py                 Job queue, run, cancel
│   ├── agents.py               Find AI CLIs, make commands
│   ├── files.py                Read and write files
│   ├── tunnel.py               Manage cloudflared
│   └── client.py               Pickle-side program (pn.py)
└── tests/

~/.pickle-network/              Data (owner access only)
├── config.json                 Settings
├── devices.json                Connected assistants, token hashes
├── jobs.sqlite3                Job records (kept 14 days)
├── jobs/                       Output of each job
├── keys/                       Tunnel data, Pickle public key
└── logs/                       Logs
```

The API specification is in [docs/API.md](docs/API.md) (Korean).

---

## 9. Security

| Risk | Action |
|---|---|
| Pickle runs commands with your user permissions | Connect only one assistant that you trust. There is no sandbox. |
| The connection message is disclosed | Run `pickle-network devices revoke pickle`. Then connect again. |
| Instructions in emails or web pages | Pickle gets rules to ignore these instructions. Examine important tasks before you request them. |
| File access is too wide | Run `pickle-network setup --root ~/projects` to limit the file folders. |
| Emergency | Run `pickle-network stop`. |

To report a vulnerability, refer to [SECURITY.md](SECURITY.md) (Korean).

---

## 10. Troubleshooting

| Problem | Cause | Action |
|---|---|---|
| Pickle cannot connect | The Quick Tunnel address changed after a restart | Run `pickle-network pair --replace --copy`. Send the result to Pickle. |
| Pickle cannot connect | The Mac is in sleep mode | Wake the Mac. Change the sleep settings. |
| An AI tool is not in the list | The PATH did not update after installation | Run `pickle-network setup` again. |
| `pickle-network` is not found | Terminal did not update the PATH | Open a new Terminal window. |
| A job does not stop | The job is long | Tell Pickle to cancel the job. |

---

## 11. FAQ

<details>
<summary><b>Do I need a Cloudflare account?</b></summary>

No. `tunnel quick` makes a temporary address without an account. For a fixed address, refer to [docs/DOMAIN.md](docs/DOMAIN.md) (Korean). A fixed address needs a Cloudflare account and a domain.

</details>

<details>
<summary><b>Can I connect a different assistant?</b></summary>

Yes, if it can use Python and HTTPS. Give each assistant a different name with `pickle-network pair --name NAME`.

</details>

<details>
<summary><b>Can I run interactive commands?</b></summary>

No. Standard input is empty. Use a non-interactive option, for example `-y`.

</details>

<details>
<summary><b>Can I close the Mac?</b></summary>

Pickle cannot connect while the Mac is in sleep mode. Connect the power adapter and change the sleep settings. Pickle Network does not change the power settings.

</details>

---

## 12. Uninstall

```bash
pickle-network uninstall --purge
rm -rf ~/pickle-network
```

`--purge` moves `~/.pickle-network` to the Trash. When you remove the server, the Pickle connection stops.

---

## 13. License

[MIT License](LICENSE)

Pickle Network is a personal project. It has no relation to Pickle, Inc. Pickle is a trademark of Pickle, Inc.
