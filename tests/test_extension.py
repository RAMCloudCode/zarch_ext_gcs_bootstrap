import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zarch_ext_gcs_bootstrap.extension import Extension


class DummyContext:
    def __init__(self, *, project_id="demo-project", region="us-central1", responder=None):
        self.id = project_id
        self.region = region
        self._responder = responder or (lambda args: ("{}", 0))
        self.gcloud_calls = []
        self.logs = []

    def gcloud(self, args):
        self.gcloud_calls.append(list(args))
        return self._responder(args)

    def log(self, message, level=None):
        self.logs.append((message, level))


def test_resolve_settings_parses_and_normalizes_values():
    ext = Extension()
    ctx = DummyContext(region="us-central1")
    cfg = {
        "config": {
            "bucket_name": "example-bucket",
            "location": "us-central1",
            "storage_class": "nearline",
            "retention_days": "45",
            "uniform_bucket_level_access": "true",
            "public_access_prevention": "false",
        }
    }

    resolved = ext._resolve_settings(cfg, ctx)

    assert resolved["bucket_name"] == "example-bucket"
    assert resolved["location"] == "US-CENTRAL1"
    assert resolved["storage_class"] == "NEARLINE"
    assert resolved["retention_days"] == 45
    assert resolved["uniform_bucket_level_access"] is True
    assert resolved["public_access_prevention"] is False


def test_resolve_settings_rejects_invalid_storage_class_or_retention():
    ext = Extension()
    ctx = DummyContext()

    with pytest.raises(RuntimeError, match="Invalid storage_class"):
        ext._resolve_settings({"config": {"storage_class": "invalid"}}, ctx)

    with pytest.raises(RuntimeError, match="retention_days must be a positive integer"):
        ext._resolve_settings({"config": {"retention_days": 0}}, ctx)


def test_bucket_create_command_shape_when_bucket_missing():
    ext = Extension()
    calls = []

    def responder(args):
        calls.append(list(args))
        if args[:3] == ["storage", "buckets", "describe"]:
            return ("Bucket not found", 1)
        return ("{}", 0)

    ctx = DummyContext(responder=responder)
    ext.post_project_bootstrap(ctx, {"config": {"bucket_name": "shape-bucket"}})

    create_calls = [c for c in calls if c[:3] == ["storage", "buckets", "create"]]
    assert len(create_calls) == 1
    create_call = create_calls[0]
    assert create_call[3] == "gs://shape-bucket"
    assert "--location=US-CENTRAL1" in create_call
    assert "--default-storage-class=STANDARD" in create_call
    assert "--uniform-bucket-level-access" in create_call
    assert "--public-access-prevention=enforced" in create_call
    assert "--project" in create_call


def test_lifecycle_update_command_shape_when_rule_missing():
    ext = Extension()
    calls = []
    bucket_json = (
        '{"location":"US-CENTRAL1","storageClass":"STANDARD",'
        '"iamConfiguration":{"uniformBucketLevelAccess":{"enabled":true},'
        '"publicAccessPrevention":"enforced"}}'
    )

    def responder(args):
        calls.append(list(args))
        if args[:3] == ["storage", "buckets", "describe"]:
            return (bucket_json, 0)
        return ("{}", 0)

    ctx = DummyContext(responder=responder)
    ext.post_project_bootstrap(ctx, {"config": {"bucket_name": "lifecycle-bucket"}})

    update_calls = [c for c in calls if c[:3] == ["storage", "buckets", "update"]]
    assert len(update_calls) == 1
    update_call = update_calls[0]
    assert update_call[3] == "gs://lifecycle-bucket"
    assert any(part.startswith("--lifecycle-file=") for part in update_call)
    assert "--project" in update_call


def test_idempotency_skips_create_and_update_when_bucket_already_compliant():
    ext = Extension()
    calls = []
    bucket_json = (
        '{"location":"US-CENTRAL1","storageClass":"STANDARD",'
        '"iamConfiguration":{"uniformBucketLevelAccess":{"enabled":true},'
        '"publicAccessPrevention":"enforced"},'
        '"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}}'
    )

    def responder(args):
        calls.append(list(args))
        if args[:3] == ["storage", "buckets", "describe"]:
            return (bucket_json, 0)
        return ("{}", 0)

    ctx = DummyContext(responder=responder)
    ext.post_project_bootstrap(
        ctx,
        {
            "config": {
                "bucket_name": "idempotent-bucket",
                "retention_days": 30,
            }
        },
    )

    create_calls = [c for c in calls if c[:3] == ["storage", "buckets", "create"]]
    update_calls = [c for c in calls if c[:3] == ["storage", "buckets", "update"]]
    assert create_calls == []
    assert update_calls == []
