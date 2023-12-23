# Home Assistant Add-on: My NGINX

## How to use

1. And you need to add the `trusted_proxies` section (requests from reverse proxies will be blocked if these options are not set).

   ```yaml
   http:
     use_x_forwarded_for: true
     trusted_proxies:
       - 172.30.33.0/24
   ```

2. Put `nginx_http.conf` file in config directory. It will be included in `http` section of NGINX config.

