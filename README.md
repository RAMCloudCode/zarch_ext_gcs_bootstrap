# Z-Arch Extension: gcs-bootstrap

`gcs-bootstrap` bootstraps and enforces a Cloud Storage bucket used for
application upload data.

## What It Does
- Enables `storage.googleapis.com`.
- Ensures the configured bucket exists.
- Validates existing bucket shape against configured location/storage/security.
- Enforces an object lifecycle delete rule (`Delete` after `retention_days`).
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
```

## Hooks
- post_project_bootstrap

## Config Reference
| Key | Type | Default | Notes |
|---|---|---|---|
| `bucket_name` | string | `example-upload-bucket` | Required bucket name. |
``````````| `location` | string | project region | Bucket location/region (upper-cased internally). |
| `storage_class` | string | `STANDARD` | One of `STANDARD`, `NEARLINE`, `COLDLINE`, `ARCHIVE`. |
| `retention_days` | integer | `30` | Lifecycle delete age in days, must be positive. |
| `uniform_bucket_level_access` | boolean | `true` | Expected UBLA state for existing buckets. |
| `public_access_prevention` | boolean | `true` | Expected PAP mode (`enforced` when true). |

## Install (MCP workflow)
Use MCP `install_extension` after the extension block is present in `zarch.yaml`.
