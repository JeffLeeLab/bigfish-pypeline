# nginx Snippet For `/napari/`

Use this snippet in your site config on the VM (not committed under `/etc/nginx/` by this repo).

## Recommended file (Oracle Linux)
- `/etc/nginx/conf.d/napari.conf`

## Snippet
```nginx
# Place this block above any catch-all `location /` proxy blocks.
location /napari/ {
    proxy_pass http://127.0.0.1:16080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

## Optional network restriction example
Apply your university/VPN ranges according to local policy.

```nginx
location /napari/ {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    proxy_pass http://127.0.0.1:16080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

## Validate and reload
```bash
sudo nginx -t
sudo systemctl reload nginx
```
