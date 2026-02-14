from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Mapping

from zarch.extensions.base import ZArchExtension


DEFAULT_CONFIG: Dict[str, Any] = {
    "bucket_name": "example-upload-bucket",
    "location": "us-central1",
    "storage_class": "STANDARD",
    "retention_days": 30,
    "uniform_bucket_level_access": True,
    "public_access_prevention": True,
}

ALLOWED_STORAGE_CLASSES = {"STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"}
BOOL_TRUE_VALUES = {"true", "1", "yes", "y", "on"}
BOOL_FALSE_VALUES = {"false", "0", "no", "n", "off"}


class Extension(ZArchExtension):
    """
    Z-Arch extension: gcs-bootstrap
    """

    def claim(self, extension_name: str, extension_block: Dict[str, Any]) -> bool:
        return extension_block.get("type") == "gcs-bootstrap"


    def post_project_bootstrap(
        self,
        project_context,
        extension_configuration: Dict[str, Any],
    ) -> None:
        settings = self._resolve_settings(extension_configuration, project_context)
        bucket_name = settings["bucket_name"]

        project_context.log("gcs-bootstrap: enabling required APIs.")
        self._run_gcloud(
            project_context,
            ["services", "enable", "storage.googleapis.com", "--quiet"],
            "enable Cloud Storage API",
        )

        project_context.log(
            f"gcs-bootstrap: ensuring bucket '{bucket_name}' exists with expected settings."
        )
        bucket, created = self._ensure_bucket(project_context, settings)
        if created:
            project_context.log(
                f"gcs-bootstrap: created bucket '{bucket_name}'.",
                level="info",
            )
        else:
            project_context.log(
                f"gcs-bootstrap: bucket '{bucket_name}' already exists.",
                level="info",
            )

        if self._has_delete_rule(bucket, int(settings["retention_days"])):
            project_context.log(
                "gcs-bootstrap: lifecycle delete rule already matches retention_days.",
                level="info",
            )
        else:
            self._update_lifecycle_rule(
                project_context=project_context,
                bucket_name=str(settings["bucket_name"]),
                retention_days=int(settings["retention_days"]),
            )
            project_context.log(
                "gcs-bootstrap: lifecycle delete rule updated.",
                level="info",
            )

    def _resolve_settings(
        self,
        extension_configuration: Mapping[str, Any],
        project_context,
    ) -> Dict[str, Any]:
        if not isinstance(extension_configuration, Mapping):
            raise RuntimeError("gcs-bootstrap config must be a mapping.")

        config_values: Dict[str, Any] = {}
        nested = extension_configuration.get("config")
        if isinstance(nested, Mapping):
            config_values.update(nested)
        else:
            config_values.update(extension_configuration)

        merged = dict(DEFAULT_CONFIG)
        merged.update(config_values)

        bucket_name = str(merged.get("bucket_name", "")).strip()
        if not bucket_name:
            raise RuntimeError("bucket_name is required and must be non-empty.")
        merged["bucket_name"] = bucket_name

        location = str(merged.get("location") or project_context.region).strip().upper()
        if not location:
            raise RuntimeError("location is required and must be non-empty.")
        merged["location"] = location

        storage_class = str(merged.get("storage_class", "")).strip().upper()
        if storage_class not in ALLOWED_STORAGE_CLASSES:
            raise RuntimeError(
                "Invalid storage_class. Expected one of: "
                + ", ".join(sorted(ALLOWED_STORAGE_CLASSES))
            )
        merged["storage_class"] = storage_class

        retention_days = self._parse_int(merged.get("retention_days"), "retention_days")
        if retention_days <= 0:
            raise RuntimeError("retention_days must be a positive integer.")
        merged["retention_days"] = retention_days

        merged["uniform_bucket_level_access"] = self._parse_bool(
            merged.get("uniform_bucket_level_access"),
            "uniform_bucket_level_access",
        )
        merged["public_access_prevention"] = self._parse_bool(
            merged.get("public_access_prevention"),
            "public_access_prevention",
        )

        return merged

    def _ensure_bucket(
        self,
        project_context,
        settings: Mapping[str, Any],
    ) -> tuple[Dict[str, Any], bool]:
        bucket_name = str(settings["bucket_name"])
        bucket_uri = f"gs://{bucket_name}"

        describe_output, describe_code = self._gcloud_with_project(
            project_context,
            ["storage", "buckets", "describe", bucket_uri, "--format=json"],
        )
        if describe_code == 0:
            bucket = self._parse_json(describe_output, "bucket describe output")
            if not isinstance(bucket, dict):
                raise RuntimeError(
                    "Expected object JSON in bucket describe output, "
                    f"got {type(bucket).__name__}."
                )
            self._validate_bucket_shape(bucket, settings)
            return bucket, False

        if not self._is_not_found_error(describe_output):
            raise RuntimeError(
                f"Failed to describe bucket '{bucket_name}': {describe_output}"
            )

        pap_mode = (
            "--pap"
            if bool(settings["public_access_prevention"])
            else "--no-pap"
        )
        ubla_flag = (
            "--uniform-bucket-level-access"
            if bool(settings["uniform_bucket_level_access"])
            else "--no-uniform-bucket-level-access"
        )
        self._run_gcloud(
            project_context,
            [
                "storage",
                "buckets",
                "create",
                bucket_uri,
                f"--location={settings['location']}",
                f"--default-storage-class={settings['storage_class']}",
                ubla_flag,
                pap_mode,
                "--quiet",
            ],
            f"create bucket '{bucket_name}'",
        )

        # Return minimal known metadata to drive lifecycle reconciliation.
        return {"name": bucket_name}, True

    def _validate_bucket_shape(
        self,
        bucket: Mapping[str, Any],
        settings: Mapping[str, Any],
    ) -> None:
        mismatches: list[str] = []

        expected_location = str(settings["location"]).upper()
        actual_location = str(bucket.get("location", "")).strip().upper()
        if actual_location and actual_location != expected_location:
            mismatches.append(
                f"location expected={expected_location} actual={actual_location}"
            )

        expected_storage_class = str(settings["storage_class"]).upper()
        actual_storage_class = str(bucket.get("storageClass", "")).strip().upper()
        if actual_storage_class and actual_storage_class != expected_storage_class:
            mismatches.append(
                "storage_class expected="
                f"{expected_storage_class} actual={actual_storage_class}"
            )

        iam_cfg = bucket.get("iamConfiguration")
        if isinstance(iam_cfg, Mapping):
            ubla = iam_cfg.get("uniformBucketLevelAccess")
            if isinstance(ubla, Mapping):
                ubla_enabled = ubla.get("enabled")
                if ubla_enabled is not None:
                    parsed_ubla = self._parse_bool(ubla_enabled, "uniformBucketLevelAccess.enabled")
                    if parsed_ubla != bool(settings["uniform_bucket_level_access"]):
                        mismatches.append(
                            "uniform_bucket_level_access expected="
                            f"{settings['uniform_bucket_level_access']} actual={parsed_ubla}"
                        )

            pap = iam_cfg.get("publicAccessPrevention")
            if pap is not None:
                pap_str = str(pap).strip().lower()
                parsed_pap = pap_str == "enforced"
                expected_pap = bool(settings["public_access_prevention"])
                if parsed_pap != expected_pap:
                    mismatches.append(
                        "public_access_prevention expected="
                        f"{expected_pap} actual={pap_str}"
                    )

        if mismatches:
            raise RuntimeError(
                "Existing bucket settings are incompatible with extension config: "
                + "; ".join(mismatches)
            )

    def _has_delete_rule(self, bucket: Mapping[str, Any], retention_days: int) -> bool:
        lifecycle = bucket.get("lifecycle")
        if not isinstance(lifecycle, Mapping):
            return False
        rules = lifecycle.get("rule")
        if not isinstance(rules, list):
            return False

        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            action = rule.get("action")
            condition = rule.get("condition")
            if not isinstance(action, Mapping) or not isinstance(condition, Mapping):
                continue
            action_type = str(action.get("type", "")).strip().lower()
            age = condition.get("age")
            if action_type != "delete":
                continue
            try:
                age_int = int(age)
            except (TypeError, ValueError):
                continue
            if age_int == retention_days:
                return True
        return False

    def _update_lifecycle_rule(
        self,
        *,
        project_context,
        bucket_name: str,
        retention_days: int,
    ) -> None:
        rule_payload = {
            "rule": [
                {
                    "action": {"type": "Delete"},
                    "condition": {"age": retention_days},
                }
            ]
        }

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(rule_payload, tmp)
                temp_path = tmp.name

            self._run_gcloud(
                project_context,
                [
                    "storage",
                    "buckets",
                    "update",
                    f"gs://{bucket_name}",
                    f"--lifecycle-file={temp_path}",
                    "--quiet",
                ],
                f"update lifecycle for bucket '{bucket_name}'",
            )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    def _run_gcloud(self, project_context, args: list[str], action: str) -> str:
        output, code = self._gcloud_with_project(project_context, args)
        if code != 0:
            raise RuntimeError(f"Failed to {action}: {output}")
        return output

    def _gcloud_with_project(self, project_context, args: list[str]) -> tuple[str, int]:
        full_args = list(args)
        if not any(arg == "--project" or arg.startswith("--project=") for arg in full_args):
            full_args.extend(["--project", project_context.id])
        return project_context.gcloud(full_args)

    def _parse_json(self, output: str, source: str) -> Any:
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse JSON from {source}: {exc}") from exc

    def _parse_bool(self, value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in BOOL_TRUE_VALUES:
                return True
            if normalized in BOOL_FALSE_VALUES:
                return False
        raise RuntimeError(f"Invalid boolean for {field_name}: {value!r}")

    def _parse_int(self, value: Any, field_name: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid integer for {field_name}: {value!r}") from exc

    def _is_not_found_error(self, output: str) -> bool:
        lowered = (output or "").lower()
        return (
            "not found" in lowered
            or "404" in lowered
            or "does not exist" in lowered
        )
