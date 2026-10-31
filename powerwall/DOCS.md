# Home Assistant App: Powerwall

Expose pypowerwall's `dispatch_battery_power` and `resume_battery_operation` to
Home Assistant automations using a local, v1r-only HTTP API.

## Safety

**Use at your own risk.** Battery dispatch uses undocumented Tesla commands and
could void or limit your warranty. Discharging can override backup reserve and
grid export restrictions: it can leave you without backup power or export in
conflict with your utility agreement. Charging can draw grid power and may ignore
grid charging settings. Outage behavior is unverified. Review
[pypowerwall's warnings](https://github.com/jasonacox/pypowerwall/blob/main/API.md#timed-battery-dispatch-v1r-mode-only)
before enabling automations. Prefer short durations and renew only as needed.

## Setup

1. Pair an RSA key with your gateway using
   [pypowerwall's v1r setup](https://github.com/jasonacox/pypowerwall#v1r-lan-tedapi-setup---option-5):
   `python3 -m pypowerwall setup -v1r`. Complete physical verification and confirm
   the key is verified. This app does not generate or register keys.
2. Install this app, then place the paired **private** RSA PEM file in its app
   configuration directory. For this repository, that is
   `/addon_configs/3e987ee6_powerwall/`, accessible using an editor or
   file-sharing app with access to app configurations. This directory is mounted
   read-only at `/config` inside the app; it is not Home Assistant's
   `configuration.yaml` directory. Protect the private key and backups of it.
3. Configure these options in the app UI:

   ```yaml
   host: "192.168.1.50"
   gw_pwd: "FULL_GATEWAY_PASSWORD"
   rsa_key_filename: "tedapi_rsa_private.pem"
   ```

4. Start the app. Restart after changing options or replacing the key.

`host` is the gateway's LAN IP address or hostname, without `https://` or a path.
`gw_pwd` is the **full gateway password from the QR sticker**, not your Tesla
account password. pypowerwall derives the v1r login password from its last five
characters. `rsa_key_filename` is a filename within the app configuration
directory, not an absolute path; paths and links outside that directory are
rejected.

The app requires all three options and a readable, nonempty key file before
starting. It establishes and verifies a local v1r connection before starting the
HTTP service. If the gateway is unreachable or the credentials/key are invalid
or unpaired, the app logs an error and exits without opening the API port.

## Network And Transport

The HTTP service listens on port `8080` in the Supervisor's internal app network.
There are **no published host ports**, no configurable port mappings, no ingress,
and no host networking. Do not expose it through a reverse proxy or router.
It needs no Supervisor or Home Assistant API permissions.

Home Assistant Core can address the app by its internal hostname. For this
repository, use `3e987ee6-powerwall` (underscores in the app identifier
become hyphens in DNS). If installed locally or from a fork, substitute its
actual internal hostname.

This is network isolation from the LAN/internet, **not authentication or isolation
from other apps on the Supervisor network**. Other apps on that network can also
call the API. Only install trusted apps.

pypowerwall is pinned to version `0.23.1`. The app explicitly disables cloud mode,
FleetAPI, automatic mode selection, connection retry loops, failover, and Wi-Fi
fallback. Both a gateway password and an RSA key path are always supplied. It
checks v1r mode before issuing either command. A local failure returns an error,
never a cloud fallback. Outbound network access is not firewalled; the strict
transport configuration enforces this behavior in pypowerwall.

## HTTP API

### `POST /battery/dispatch`

Send `Content-Type: application/json` and exactly these fields:

```json
{"power_watts": -1500, "duration_seconds": 60}
```

- `power_watts`: finite number in watts. Positive discharges, negative charges,
  zero requests idle battery power. Booleans and numeric strings are rejected.
- `duration_seconds`: integer from `1` to `86400` inclusive.

An acknowledged command returns `200 OK` with pypowerwall's response:

```json
{"power_watts": -1500.0, "duration_seconds": 60}
```

A new dispatch replaces the active setpoint and timer. The **gateway** resumes
its configured operation when the duration expires; the app does not run a local
timer and does not wait for expiry before returning. Restarting the app does not
cancel a dispatch. Hardware/firmware operating limits still apply. An
acknowledgement confirms acceptance, not the actual measured battery power.

### `POST /battery/resume`

Send no body, or `{}` with `Content-Type: application/json`. It releases an active
dispatch early and returns `200 OK` with:

```json
{"resume_battery_operation": true}
```

This also succeeds if no dispatch is active. It does not cancel manual backup
events or change reserve, tariff, or operating mode settings.

### Errors

- `400`: invalid JSON, unexpected fields, or invalid power/duration.
- `404`: unknown endpoint; `405`: GET on either operation (POST is required).
- `409`: another gateway operation is in progress. Commands are serialized.
- `413`: request body exceeds 4096 bytes or has a negative length.
- `415`: a nonempty body was sent without `application/json`.
- `502`: local connection/authentication failed, firmware rejected the command,
  or no acknowledgement was received.

Errors are JSON objects with an `error` field. A failed operation discards the
client so the next request reconnects locally. The app never automatically retries
a command: a lost acknowledgement does not prove that the gateway ignored it.

## Home Assistant Automations

Add to Home Assistant's `configuration.yaml`, then restart Home Assistant:

```yaml
rest_command:
  powerwall_dispatch:
    url: "http://3e987ee6-powerwall:8080/battery/dispatch"
    method: POST
    content_type: "application/json"
    payload: >-
      {{ {"power_watts": power_watts,
          "duration_seconds": duration_seconds} | to_json }}
    timeout: 60

  powerwall_resume:
    url: "http://3e987ee6-powerwall:8080/battery/resume"
    method: POST
    content_type: "application/json"
    payload: "{}"
    timeout: 60
```

Example automation actions to charge at 1500 W for 60 seconds:

```yaml
actions:
  - action: rest_command.powerwall_dispatch
    data:
      power_watts: -1500
      duration_seconds: 60
```

To resume normal operation early:

```yaml
actions:
  - action: rest_command.powerwall_resume
```

Use numeric values (or templates producing numbers) rather than numeric strings.
Check the REST action's response status in automations before assuming success,
and monitor the battery's actual power using your existing HA integration.

## Development

From the repository root:

```sh
uv run --with-requirements powerwall/requirements.txt \
  python -m unittest discover -s powerwall/tests -v
```

Tests mock the gateway; they do not issue real battery commands.
