# Pickle Network

[한국어](README.md) | **English**

Ask Pickle. Your Mac does the work.

Pickle Network connects Pickle to your Mac. With this connection, Pickle runs terminal commands on your Mac. Pickle reads and writes files. Pickle sends tasks to Claude Code, Codex, Gemini CLI, and AGY. You do not need a Cloudflare account or a domain.

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

## Quick Start Prompt

Paste this text into an AI coding tool (Claude Code, Codex, or equivalent). The AI tool does the installation.

```
Clone https://github.com/hahmjuntae/pickle-network into ~/pickle-network and install it as the README says. Then show me the output of pickle-network doctor and the message that pickle-network pair prints.
```

Send the message from the AI tool to Pickle. Then do step 2 in [Pairing](#pairing).

## Requirements

- macOS
- Python 3.9 or later (included in macOS)
- Git
- [Homebrew](https://brew.sh)
- A Pickle account

## Installation

Run these commands in Terminal:

```bash
brew install cloudflared
git clone https://github.com/hahmjuntae/pickle-network.git ~/pickle-network
~/pickle-network/bin/pickle-network setup
~/pickle-network/bin/pickle-network tunnel quick
```

The last command shows an address `https://...trycloudflare.com`. The server and the tunnel start automatically when the Mac starts.

## Pairing

1. Run `pickle-network pair`. Send the printed message to Pickle.
2. Copy the public key from Pickle (`-----BEGIN PUBLIC KEY-----`). Run this command:

   ```bash
   pbpaste > ~/pickle.pub && pickle-network pair --key ~/pickle.pub --copy
   ```

3. Send the message on the clipboard to Pickle.

When Pickle sends the Mac name and the list of AI tools, the connection is complete. To examine the connection, run `pickle-network doctor`. The command output is in Korean.

## Usage

### Example Prompts

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

### Reset Prompt

If Pickle does not obey the usage rules, send this text:

```
Run python3 pn.py guide, read the pickle-network usage rules again, and obey them.
```

### Commands

| Command | Function |
|---|---|
| `pickle-network status` | Show the status and the public address |
| `pickle-network doctor` | Test the connection |
| `pickle-network pair` | Make a connection message |
| `pickle-network pair --replace --copy` | Make a new connection message after the address changes |
| `pickle-network devices` | Show the connected assistants |
| `pickle-network devices revoke pickle` | Disconnect an assistant |
| `pickle-network stop` / `start` | Stop or start the server and the tunnel |
| `pickle-network logs` | Show the server log |

## Architecture

### Request Flow

```
 Pickle                         pickle-network (127.0.0.1)
 ──────                         ──────────────────────────
 POST /v1/ask  ──────────────▶  1. check device token        → 401 if wrong
                                2. put job in queue          → up to 3 at once
                                3. run CLI in new process    → output saved live
 ◀─── result (wait ≤ 90s) ───   4. return exit code + output
 GET /v1/jobs/{id}  ─────────▶  5. still running? keep waiting or cancel
```

The server accepts requests only on `127.0.0.1`. External requests come in only through Cloudflare Tunnel. The server checks the device token for each request and keeps only a hash of each token. The server runs a maximum of 3 jobs at the same time. Pickle waits a maximum of 90 seconds for a result. For a longer job, Pickle waits again with the job ID or cancels the job.

### Pairing Sequence

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

### Directory Layout

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

## Security

Pickle runs commands with the permissions of the Mac user. There is no sandbox. Connect only one assistant that you trust.

- If the connection message is disclosed, run `pickle-network devices revoke pickle`. Then connect again.
- Pickle gets rules to ignore instructions in emails and web pages. Examine important tasks before you request them.
- To limit the file folders, run `pickle-network setup --root ~/projects`.
- In an emergency, run `pickle-network stop`.

To report a vulnerability, refer to [SECURITY.md](SECURITY.md) (Korean).

## Troubleshooting

| Problem | Cause | Action |
|---|---|---|
| Pickle cannot connect | The Quick Tunnel address changed after a restart | Send the result of `pickle-network pair --replace --copy` to Pickle. |
| Pickle cannot connect | The Mac is in sleep mode | Wake the Mac. Change the sleep settings. |
| An AI tool is not in the list | The PATH did not update after installation | Run `pickle-network setup` again. |
| `pickle-network` is not found | Terminal did not update the PATH | Open a new Terminal window. |
| A job does not stop | The job is long | Tell Pickle to cancel the job. |

## FAQ

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

## Uninstall

```bash
pickle-network uninstall --purge
rm -rf ~/pickle-network
```

`--purge` moves `~/.pickle-network` to the Trash. When you remove the server, the Pickle connection stops.

## License

[MIT License](LICENSE)

Pickle Network is a personal project. It has no relation to Pickle, Inc. Pickle is a trademark of Pickle, Inc.
