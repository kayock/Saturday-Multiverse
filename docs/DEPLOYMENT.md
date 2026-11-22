# Deployment — local, LAN, and optional HTTPS

Saturday Multiverse is a local-first application. Everything below works on
Windows and Linux with Python 3.10+. No accounts, API keys, tokens, or login
screens are involved in any of these modes.

---

## 1. Local play (default — unchanged)

```bash
python -m server.app          # Linux/macOS   (or: ./run.sh)
python -m server.app          # Windows       (or: run.bat)
```

The server listens on `127.0.0.1:8788`. Open
[http://127.0.0.1:8788](http://127.0.0.1:8788). Nothing about this mode has
changed.

Production-style serving (optional):

```bash
SATURDAY_PRODUCTION=1 python -m server.app   # waitress WSGI server
```

### Linux install

```bash
git clone https://github.com/kayock/Saturday-Multiverse.git
cd Saturday-Multiverse
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
SATURDAY_PRODUCTION=1 .venv/bin/python -m server.app
```

Campaigns, imported books, and certificates belong in a data directory
outside the checkout, for example:

```bash
export SATURDAY_DATA_DIR="$HOME/.local/share/saturday-multiverse"
```

To start it with the user session, copy
`deploy/saturday-multiverse.service.example` to
`~/.config/systemd/user/saturday-multiverse.service`, replace the
placeholders, then `systemctl --user enable --now saturday-multiverse.service`.
Keep real addresses and paths in that local unit. Do not commit them.

Optional Game Master routing, still local:

```bash
SATURDAY_GM_AUTO=1
SATURDAY_GM_STATION_URL=http://127.0.0.1:11434/v1
SATURDAY_GM_PORTABLE_URL=http://192.168.1.20:11434/v1
SATURDAY_GM_PRIMARY=your-lightweight-model
SATURDAY_GM_FALLBACK=your-other-lightweight-model
```

Leave the portable URL empty on a one-computer install. The game remains
playable with the Offline Storyteller when neither model answers.

## 2. LAN play over plain HTTP

Other devices on the same network reach the same game when the server binds
to all interfaces:

```bash
SATURDAY_HOST=0.0.0.0 python -m server.app
# Windows (PowerShell):
#   $env:SATURDAY_HOST="0.0.0.0"; python -m server.app
```

The startup banner prints the address. Find the hosting computer's LAN IP:

- **Linux/macOS:** `hostname -I` or `ipconfig getifaddr en0`
- **Windows:** `ipconfig` (look for *IPv4 Address*, e.g. `192.168.1.20`)

Then, on any other device's browser: `http://192.168.1.20:8788`.

**Solo play from another LAN device needs no lobby.** A remote browser uses
the ordinary title screen → *New Voyage* → play; the campaign state lives on
the hosting computer and resumes across browsers. All frontend requests use
relative URLs, so the page works identically from any address the server is
reached on. Switching devices mid-voyage just re-opens the same campaign —
no duplicate characters are created (multiplayer guests always join through
an invitation, which is the only path that creates characters).

**Multiplayer over LAN:** the hosting player presses *Host a Shared Voyage*,
creates an invitation, and other devices join with the link
(`http://<lan-ip>:8788/?join=<token>`). Ownership rules, spectator filtering
and split-party knowledge behave exactly as documented in
[docs/MULTIPLAYER.md](MULTIPLAYER.md).

> The plain-HTTP LAN mode trusts everyone on your network the way a shared
> notebook would — that is the game's long-standing access model. For
> encryption, use the HTTPS mode below.

## 2.1 Startup modes at a glance (hotfix 2)

The startup banner and `/api/health` always state the ACTUAL listener
protocol — the advertised URL never lies about the port:

| Mode | Environment | Listener | Banner shows |
| --- | --- | --- | --- |
| A | (nothing) | plain HTTP | `http://host:8788` |
| B | `SATURDAY_TLS=1` | **HTTPS** (this process) | `https://host:8788` |
| C | `SATURDAY_PRODUCTION=1` | waitress, plain HTTP | `http://host:8788` |
| D | `SATURDAY_PRODUCTION=1 SATURDAY_TLS=1` | **plain HTTP** (waitress cannot terminate TLS) | explicit note: "this port serves PLAIN HTTP; TLS happens at your local reverse proxy"; external HTTPS URL only if `SATURDAY_TLS_PROXY_URL=https://…` is set |
| E | `SATURDAY_PRODUCTION=1 SATURDAY_TLS=1 SATURDAY_TLS_DEVSERVER=1` | **HTTPS** (this process) | `https://host:8788` |

`GET /api/health` reports `listener` ("http"/"https") and `tls.mode`
("off"/"direct"/"proxy") so monitoring and scripts see the same truth.

If HTTPS is requested with an unusable certificate, startup FAILS with an
actionable message instead of serving the bad certificate — see §3.8.

## 3. LAN play over HTTPS (optional, explicitly enabled)

HTTPS adds encryption between the hosting computer and other devices. It
uses a small **local certificate authority (CA)** that lives only on the
hosting computer. Nothing is ever installed automatically, no cloud service
or public domain is required, and HTTPS is off unless you turn it on.

### 3.1 One-time certificate setup (hosting computer)

```bash
python scripts/cert_setup.py generate
```

This creates, inside your data directory (`userdata/certs/`, or the path set
by `SATURDAY_DATA_DIR`):

| File | Purpose | Distribution |
| --- | --- | --- |
| `saturday-lan-ca.crt` | the local CA's **public** certificate | clients install this to trust the server (only if you choose to) |
| `saturday-lan-ca.key` | the CA **private key** | **never leaves this computer** |
| `saturday-server.crt` | the server certificate (SANs for localhost + LAN IPs + hostname) | stays on the server |
| `saturday-server.key` | the server private key (permissions `0600` on Linux/macOS) | stays on the server |

The tool prints the **CA fingerprint (SHA-256)** — compare it on a client
before trusting the CA there.

Already have a certificate? Use it instead:

```bash
SATURDAY_TLS_CERT=/path/server.crt SATURDAY_TLS_KEY=/path/server.key python -m server.app
```

### 3.2 Enable HTTPS

```bash
SATURDAY_TLS=1 SATURDAY_HOST=0.0.0.0 python -m server.app
```

- The banner now shows `https://…`.
- Ordinary HTTP behavior is unchanged when `SATURDAY_TLS` is not set; the
  default port and startup scripts are untouched.
- With `SATURDAY_PRODUCTION=1`, the waitress WSGI server cannot terminate
  TLS itself. Two supported paths:
  1. `SATURDAY_TLS_DEVSERVER=1` — serve HTTPS directly (fine for a home LAN);
  2. keep waitress on plain HTTP and terminate TLS at a local reverse proxy
     (see 3.6). Forwarded headers are honored **only** with the explicit
     `SATURDAY_TRUST_PROXY=1`.

### 3.3 Trust the local CA on client devices (manual, per device)

A home-LAN CA is not automatically trusted. Until you complete this step on
a device, its browser shows the standard certificate warning — that is
expected and honest; it is not a broken server.

**Verify first:** the CA fingerprint shown by `python scripts/cert_setup.py
show` on the host must match what the client is about to install.

**Windows 10/11**
1. Double-click `saturday-lan-ca.crt` → *Install Certificate…*
2. Store location: **Local Machine** (or Current User).
3. Place in: **Trusted Root Certification Authorities**.
4. Restart the browser.

**Linux (Chromium/Firefox)**
- System store (Debian/Ubuntu): `sudo cp saturday-lan-ca.crt
  /usr/local/share/ca-certificates/saturday-lan-ca.crt && sudo update-ca-certificates`
- Firefox keeps its own store: Settings → Privacy & Security → Certificates →
  *View Certificates* → Authorities → Import → tick "trust websites".

**Android**
1. Copy `saturday-lan-ca.crt` onto the device.
2. Settings → Security → *Install a certificate* → **CA certificate**.
3. Android marks user-added CAs; Chrome ≥ 105 trusts them for user traffic.

**iOS/iPadOS**
1. Open the `.crt` file (AirDrop/Mail/Files) → *Install Profile*.
2. Settings → General → About → **Certificate Trust Settings** → enable full
   trust for `Saturday Multiverse Local CA`.

macOS: double-click the certificate in Keychain Access → *System* keychain →
open it → Trust → *Always Trust* (SSL).

Never install the CA on a device you do not control, and never distribute
`saturday-lan-ca.key` — clients only ever need the public `.crt`.

### 3.35 Naming the client-facing address (SAN validation)

Certificates are validated against the names a BROWSER would use — never
against `0.0.0.0`, which is a bind address, not an identity:

- `SATURDAY_TLS_NAME=192.168.1.20` (or a hostname) pins the expected
  client-facing name; startup refuses a certificate that does not cover it.
- Without it, coverage is checked against every non-loopback address of the
  machine plus the hostname plus localhost; a certificate covering none of
  them is refused, and partial coverage prints exactly which names are
  covered and which are missing.

**Strict SAN identities (hotfix 3).** Coverage is decided by the actual
Subject Alternative Name extension — nothing else:

- A certificate with **no SAN extension is refused**, even when its Common
  Name matches the configured name. Modern browsers require SAN identities;
  the CN is reported by `diagnose` (field `cn`) for information only and
  never satisfies a requirement.
- A name that parses as an **IP address is covered only by a real
  `IPAddress` SAN**. A `DNSName` entry that merely contains the textual IP
  (e.g. `DNS:192.168.1.20`) is NOT an IP identity and does not cover it —
  browsers apply the same rule. The generated certificates always carry
  `IPAddress` entries for every LAN address; `renew --ip <address>` re-adds
  them as IP SANs.
- Hostnames match their DNS SAN entries case-insensitively.

### 3.36 Certificate validity windows (hotfix 3)

Validation compares the certificate's exact validity interval in
timezone-aware UTC — no whole-day rounding that could misclassify a
certificate near a boundary:

- current time **before `not_valid_before`** → `certificate NOT YET VALID —
  becomes valid …` and startup is refused (check the system clock, or
  re-issue the certificate);
- current time **after `not_valid_after`** → `certificate EXPIRED … days
  ago` and startup is refused;
- unreadable files, a private key that does not match, or missing required
  identities are refused as before.

`days_left` (in diagnostics and `/api/health`) keeps its meaning for the
30-day renewal warning; the pass/refuse decision itself is exact-time.

### 3.4 Renewal and changed addresses

Server certificates are issued for **825 days** (~27 months). The CA lasts
~10 years. Renew when expired, or when the LAN IP/hostname changed:

```bash
python scripts/cert_setup.py renew     # same CA, fresh server certificate
python scripts/cert_setup.py diagnose  # check expiry, key match, SAN coverage
python scripts/cert_setup.py show      # paths, SANs, CA fingerprint
```

`renew` reads the machine's current addresses automatically; pass
`--ip 192.168.1.50` to cover an address that is not auto-detected. Clients
do **not** need to re-trust anything after a server-certificate renewal —
only after the CA itself is replaced (`generate --force`).

Diagnostics on startup: a missing, expired, invalid or mismatched
certificate is reported in clear language on the console and in
`/api/health` (`"tls": {"certificate_ok": …, "days_left": …, "problems": …}`),
and `python scripts/preflight.py` checks it too. The server never serves
HTTPS silently with a broken certificate.

### 3.45 SAN mismatch recovery (hotfix 2)

When startup reports `certificate does not cover the configured HTTPS name
'…'` or `covers NONE of the client-facing names`:

1. Confirm the address players actually type (e.g. `192.168.1.20:8788`).
2. Renew with that name: `python scripts/cert_setup.py renew --ip 192.168.1.20`
   (repeat `--ip` for each address in use).
3. Re-check: `python scripts/cert_setup.py diagnose` →
   "covers client-facing names" must list the address.
4. Restart with `SATURDAY_TLS=1`. Clients do NOT need to re-trust anything —
   the local CA is unchanged; only the server certificate was renewed.

Other hard failures (expired, key mismatch, missing files) name their fix:
renew, re-copy the pair, or point `SATURDAY_TLS_CERT/KEY` at a valid PEM pair.
An expired user certificate is never replaced automatically.

### 3.5 Troubleshooting HTTPS and SSE

| Symptom | Cause and fix |
| --- | --- |
| Browser warning on first visit | CA not (yet) trusted on that client — see 3.3; the warning disappears after trusting |
| `ERR_CERT_AUTHORITY_INVALID` | the client trusts a different CA — compare fingerprints |
| `ERR_CERT_COMMON_NAME_INVALID` | you opened an address not in the SANs — renew with `--ip <address>` |
| Startup: `no Subject Alternative Names` | the certificate carries only a Common Name (hotfix 3 refuses CN-only certificates) — re-issue with SANs: `cert_setup.py generate`, or provide a pair with a real SAN extension |
| Startup: `certificate NOT YET VALID` | the certificate's validity begins in the future — check the machine's clock, or re-issue with a back-dated start (`generate` back-dates one day by design) |
| Startup: `does not cover … with a matching IPAddress SAN` | the address is covered only by a DNS name containing the textual IP — renew with `--ip <address>` so a real `IPAddress` SAN is written |
| Server refuses to start with HTTPS | missing certificate — run `cert_setup.py generate` or set `SATURDAY_TLS_CERT/KEY` |
| SSE stalls behind a proxy | allow long-lived responses (Caddy: default; nginx: `proxy_buffering off; proxy_read_timeout 300s;`) |
| Mixed content warnings | open the page via the same scheme it serves (`https://…` when `SATURDAY_TLS=1`); all assets are same-origin relative URLs |

### 3.6 Optional: Caddy as TLS terminator (production style)

Not required, not bundled — an option for those who prefer a dedicated proxy
in front of waitress:

```
# Caddyfile — LAN HTTPS in front of Saturday Multiverse
{
  local_certs                       # or point tls at the Saturday CA files
}
https://192.168.1.20:8443 {
  tls /path/to/saturday-server.crt /path/to/saturday-server.key
  reverse_proxy 127.0.0.1:8788
}
```

Run the game with `SATURDAY_PRODUCTION=1 SATURDAY_TRUST_PROXY=1` so
X-Forwarded-* headers are honored (only when a local proxy actually sits in
front). SSE works through Caddy without extra configuration.

### 3.7 What HTTPS does NOT add

No accounts, no passwords, no tokens, no login screens, no cloud
dependencies, no DNS/public-domain requirements, and no automatic trust-store
changes. Certificates for arbitrary private IPs cannot come from public CAs —
that is a property of the public CA system, not of this application.

---

## 4. Backups, migration, and data

Backups: `POST /backup` snapshots the whole database (whole-file, WAL-safe);
restore via `POST /backups/<id>/restore`. Schema migrations are additive and
versioned (`saturday.core.v7` in this release; every earlier version
migrates forward with zero data loss — see `tests/test_migrations.py`).
Certificates and keys live under `<data directory>/certs/` and are excluded
from backups' distribution, Git, and release packages.
