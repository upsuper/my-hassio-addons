# Home Assistant Add-on: Speedtest

## Configuration

- `server_id`: Optional Speedtest.net server ID. Leave this empty to let Speedtest select a server automatically.

## HTTP API

The API listens on port `8080` inside the Home Assistant add-on network. The port is not published on the host by default.

- `POST /speedtest` runs a measurement and returns `204 No Content` after it has been stored.
- `GET /speedtest` returns the latest Speedtest CLI JSON result. It returns `404 Not Found` until the first successful measurement.

Only one measurement can run at a time. A concurrent request returns `409 Conflict`; CLI failures return `502 Bad Gateway`, and measurements exceeding five minutes return `504 Gateway Timeout`.

From Home Assistant, address port `8080` on the add-on's internal hostname. The add-on has no Supervisor or Home Assistant API access, and its port is not published to the host. Its outbound network access is not restricted, because Speedtest requires internet access.

## Home Assistant configuration

Add the following to Home Assistant's `configuration.yaml`:

```yaml
rest_command:
  run_speedtest:
    url: "http://3e987ee6-speedtest:8080/speedtest"
    method: POST
    timeout: 600

rest:
  - resource: "http://3e987ee6-speedtest:8080/speedtest"
    scan_interval: 300
    sensor:
      - name: Speedtest Ping
        unique_id: speedtest_ping
        value_template: "{{ value_json.ping.latency | round(2) }}"
        device_class: duration
        unit_of_measurement: ms
        state_class: measurement
        json_attributes_path: "$.ping"
        json_attributes:
          - jitter
          - low
          - high

      - name: Speedtest Download
        unique_id: speedtest_download
        value_template: >-
          {{ ((value_json.download.bandwidth | float) * 8 / 1000000) | round(2) }}
        device_class: data_rate
        unit_of_measurement: Mbit/s
        state_class: measurement
        json_attributes_path: "$.download"
        json_attributes:
          - bytes
          - elapsed
          - latency

      - name: Speedtest Upload
        unique_id: speedtest_upload
        value_template: >-
          {{ ((value_json.upload.bandwidth | float) * 8 / 1000000) | round(2) }}
        device_class: data_rate
        unit_of_measurement: Mbit/s
        state_class: measurement
        json_attributes_path: "$.upload"
        json_attributes:
          - bytes
          - elapsed
          - latency

      - name: Speedtest Last Run
        unique_id: speedtest_last_run
        value_template: "{{ value_json.timestamp }}"
        device_class: timestamp
        json_attributes:
          - isp
          - interface
          - server
          - result
```

Restart Home Assistant after changing the configuration. Run a measurement by invoking the `rest_command.run_speedtest` action. The command waits for the measurement to finish, which can take several minutes. The sensors fetch the latest result every five minutes and are unavailable until the first successful measurement.

The hostname `3e987ee6-speedtest` is generated from this repository URL and the add-on slug. If the add-on is installed as a local add-on instead, use `local-speedtest`.

Speedtest CLI reports download and upload `bandwidth` in bytes per second. The templates convert these values to megabits per second. Home Assistant has no sensor device class specifically for packet loss, so that sensor intentionally has only a percentage unit and measurement state class.

Running a measurement passes Speedtest CLI's license and GDPR acceptance flags. By using this add-on, you agree to Ookla's Speedtest CLI license and privacy terms.
