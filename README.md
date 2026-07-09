# Z-Arch Extension: gcs-bootstrap

`gcs-bootstrap` bootstraps and enforces a Cloud Storage bucket used for
application upload data.

## What It Does
- Enables `storage.googleapis.com`.
- Ensures the configured bucket exists.
- Validates existing bucket shape against configured location/storage/security.
- Enforces an object lifecycle delete rule (`Delete` after `retention_days`).
- Optionally enforces a bucket CORS configuration.
- Is idempotent for already-compliant buckets.

## zarch.yaml Example
```yaml
extensions:
  gcs-bootstrap:
    type: "gcs-bootstrap"
    required_roles:
      - "roles/storage.admin"
      - "roles/serviceusage.serviceUsageAdmin"
    config:
      bucket_name: "upload-bucket"
      location: "us-central1"
      storage_class: "STANDARD"
      retention_days: 30
      uniform_bucket_level_access: true
      public_access_prevention: true
      cors:
        - origins:
            - "https://terminal.example.com"
          methods:
            - "PUT"
            - "OPTIONS"
          response_headers:
            - "Content-Type"
          max_age_seconds: 3600
```

## Hooks
- `async post_project_bootstrap`

## Config Reference
| Key | Type | Default | Notes |
|---|---|---|---|
| `bucket_name` | string | `example-upload-bucket` | Required bucket name. |
| `location` | string | project region | Bucket location/region (upper-cased internally). |
| `storage_class` | string | `STANDARD` | One of `STANDARD`, `NEARLINE`, `COLDLINE`, `ARCHIVE`. |
| `retention_days` | integer | `30` | Lifecycle delete age in days, must be positive. |
| `uniform_bucket_level_access` | boolean | `true` | Expected UBLA state for existing buckets. |
| `public_access_prevention` | boolean | `true` | Expected PAP mode (`enforced` when true). |
| `cors` | list[object] \| null | `null` | When omitted/null, CORS is unmanaged. When provided, the bucket CORS config is enforced exactly. |

### CORS Rule Shape
Each `cors` rule uses Z-Arch-style snake_case keys:

```yaml
origins: ["https://terminal.example.com"]
methods: ["PUT", "OPTIONS"]
response_headers: ["Content-Type"]
max_age_seconds: 3600
```

The extension normalizes this to the Cloud Storage JSON CORS shape:
`origin`, `method`, `responseHeader`, and `maxAgeSeconds`.

## Install (MCP workflow)
Use MCP `install_extension` after the extension block is present in `zarch.yaml`.
