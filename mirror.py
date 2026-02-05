#!/usr/bin/env python3

import argparse
import fnmatch
import hashlib
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Args:
    repo: str
    revision: str
    bucket: str
    prefix: str
    include: Optional[str]
    exclude: Optional[str]
    dry_run: bool
    keep_local: bool
    local_dir: Optional[str]
    zip_name: Optional[str]
    force: bool


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_dotenv_if_present() -> None:
    """Best-effort .env loader (no third-party dependency).

    Loads KEY=VALUE pairs from a `.env` file if present in either the current
    working directory or alongside this script. Existing environment variables
    are not overwritten.
    """

    def _try_load(dotenv_path: Path) -> None:
        if not dotenv_path.exists() or not dotenv_path.is_file():
            return
        try:
            for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line.removeprefix("export ").lstrip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or key in os.environ:
                    continue
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                os.environ[key] = value
        except Exception:
            # Never fail the program due to dotenv parsing.
            return

    _try_load(Path.cwd() / ".env")
    _try_load(Path(__file__).resolve().parent / ".env")


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _matches_any(path: str, patterns_csv: Optional[str]) -> bool:
    if not patterns_csv:
        return False
    patterns = [p.strip() for p in patterns_csv.split(",") if p.strip()]
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def _should_upload(rel_posix: str, include: Optional[str], exclude: Optional[str]) -> bool:
    if include and not _matches_any(rel_posix, include):
        return False
    if exclude and _matches_any(rel_posix, exclude):
        return False
    return True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _s3_key(prefix: str, rel_posix: str) -> str:
    prefix = prefix.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{rel_posix}"


def _normalize_bucket(bucket: str) -> str:
    bucket = bucket.strip()
    if bucket.startswith("arn:aws:s3:::"):
        return bucket.removeprefix("arn:aws:s3:::").strip("/")
    if bucket.startswith("s3://"):
        return bucket.removeprefix("s3://").split("/", 1)[0]
    return bucket


def _s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError:
        return False


def parse_args(argv: list[str]) -> Args:
    p = argparse.ArgumentParser(description="Mirror a Hugging Face model repo (gated OK) into S3")
    p.add_argument("--repo", required=True, help="Hugging Face repo id, e.g. ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large")
    p.add_argument("--revision", default="main", help="Branch/tag/commit. Default: main")
    p.add_argument("--bucket", required=True, help="S3 bucket name")
    p.add_argument("--prefix", default="", help="S3 prefix (folder) to upload into")
    p.add_argument(
        "--include",
        default=None,
        help="Comma-separated glob(s) to include (relative paths), e.g. '*.nemo,*.json'. If omitted, includes all.",
    )
    p.add_argument(
        "--exclude",
        default=None,
        help="Comma-separated glob(s) to exclude (relative paths), e.g. '*.git/*,*.md'.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print planned uploads, do not upload")
    p.add_argument("--keep-local", action="store_true", help="Keep the downloaded snapshot on disk")
    p.add_argument(
        "--local-dir",
        default=None,
        help="Optional local directory to store/download the snapshot. If omitted, uses HF cache.",
    )
    p.add_argument(
        "--zip",
        dest="zip_name",
        default=None,
        metavar="FILENAME",
        help="Instead of uploading individual files, create a zip archive and upload it. "
        "Value is the zip filename, e.g. 'qwen2.5-0.5b.zip'. Uploaded to <prefix>/<FILENAME>.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Upload even if the target already exists in S3. Without this flag, existing files are skipped.",
    )

    ns = p.parse_args(argv)
    return Args(
        repo=ns.repo,
        revision=ns.revision,
        bucket=ns.bucket,
        prefix=ns.prefix,
        include=ns.include,
        exclude=ns.exclude,
        dry_run=ns.dry_run,
        keep_local=ns.keep_local,
        local_dir=ns.local_dir,
        zip_name=ns.zip_name,
        force=ns.force,
    )


def main(argv: list[str]) -> int:
    _load_dotenv_if_present()
    args = parse_args(argv)
    bucket_name = _normalize_bucket(args.bucket)

    try:
        hf_token = _require_env("HF_TOKEN")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        import boto3
        import botocore.exceptions
        from huggingface_hub import HfApi, snapshot_download
    except Exception as e:
        print(
            "ERROR: Missing dependencies. Install with: pip install -r requirements.txt\n"
            f"Details: {e}",
            file=sys.stderr,
        )
        return 4

    # ── Set up S3 early so we can check for existing files before downloading. ──
    region_name = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    profile_name = os.getenv("AWS_PROFILE") or os.getenv("AWS_DEFAULT_PROFILE")
    session = boto3.session.Session(region_name=region_name, profile_name=profile_name)

    # Fail fast with a helpful error if no AWS credentials are available.
    try:
        creds = session.get_credentials()
    except botocore.exceptions.MissingDependencyException as e:
        # Some environments (e.g. AWS CLI v2 `aws login`) create cached credentials that
        # botocore loads via the "login" provider, which requires the CRT extra.
        print(
            "ERROR: Your AWS credentials provider requires an extra dependency.\n"
            "Install with: pip install -r requirements.txt\n"
            "(This repo includes `botocore[crt]` for AWS CLI `aws login` compatibility.)\n"
            f"Details: {e}",
            file=sys.stderr,
        )
        return 5
    except Exception as e:
        print(f"ERROR: Failed to load AWS credentials: {e}", file=sys.stderr)
        return 5

    if creds is None:
        print(
            "ERROR: No AWS credentials found. Configure one of:\n"
            "  - Environment vars: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN)\n"
            "  - A shared config/profile (AWS_PROFILE) with `aws sso login` or `aws configure`\n"
            "  - An instance/task role (EC2/ECS/IRSA)\n",
            file=sys.stderr,
        )
        return 5

    s3 = session.client("s3")

    # ── Skip if target already exists in S3 (unless --force). ──
    if not args.force and not args.dry_run and args.zip_name:
        zip_key = _s3_key(args.prefix, args.zip_name)
        if _s3_key_exists(s3, bucket_name, zip_key):
            print(f"SKIP: s3://{bucket_name}/{zip_key} already exists. Use --force to re-upload.")
            return 0

    # ── Download from Hugging Face. ──
    # Quick auth check (fail fast for gated repos)
    api = HfApi(token=hf_token)
    try:
        api.model_info(args.repo, revision=args.revision)
    except Exception as e:
        print(f"ERROR: Unable to access repo '{args.repo}' (revision={args.revision}): {e}", file=sys.stderr)
        return 3

    print(f"Downloading snapshot: {args.repo}@{args.revision}")
    snapshot_path = snapshot_download(
        repo_id=args.repo,
        revision=args.revision,
        token=hf_token,
        local_dir=args.local_dir,
        local_dir_use_symlinks=False,
        # We filter ourselves because HF's allow_patterns/ignore_patterns are a bit different,
        # and we want predictable relpaths for S3 keys.
    )
    root = Path(snapshot_path)

    # Collect files that pass include/exclude filters.
    matched_files: list[tuple[Path, str]] = []  # (absolute_path, rel_posix)
    for file_path in _iter_files(root):
        rel_posix = file_path.relative_to(root).as_posix()
        if _should_upload(rel_posix, args.include, args.exclude):
            matched_files.append((file_path, rel_posix))

    if args.zip_name:
        # -- Zip mode: bundle matched files into a single archive and upload it.
        zip_key = _s3_key(args.prefix, args.zip_name)

        if args.dry_run:
            print(f"DRY-RUN zip → s3://{bucket_name}/{zip_key}  ({len(matched_files)} file(s))")
            for _, rel in matched_files:
                print(f"  {rel}")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / args.zip_name
                total = len(matched_files)
                print(f"Creating zip ({total} files): {args.zip_name}")
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
                    for i, (file_path, rel_posix) in enumerate(matched_files, 1):
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        print(f"  [{i}/{total}] {rel_posix} ({size_mb:.1f} MB)")
                        zf.write(file_path, arcname=rel_posix)

                zip_sha256 = _sha256_file(zip_path)
                zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
                print(f"Uploading s3://{bucket_name}/{zip_key} ({zip_size_mb:.1f} MB)")
                s3.upload_file(
                    Filename=str(zip_path),
                    Bucket=bucket_name,
                    Key=zip_key,
                    ExtraArgs={
                        "Metadata": {
                            "hf_repo": args.repo,
                            "hf_revision": args.revision,
                            "sha256": zip_sha256,
                        }
                    },
                )
            print(f"Done. uploaded=1 (zip with {total} files)")
    else:
        # -- Normal mode: upload each file individually.
        planned = 0
        uploaded = 0
        skipped = 0

        for file_path, rel_posix in matched_files:
            key = _s3_key(args.prefix, rel_posix)
            planned += 1

            if args.dry_run:
                print(f"DRY-RUN upload s3://{bucket_name}/{key}  <-  {rel_posix}")
                continue

            if not args.force and _s3_key_exists(s3, bucket_name, key):
                print(f"SKIP (exists): s3://{bucket_name}/{key}")
                skipped += 1
                continue

            sha256 = _sha256_file(file_path)

            print(f"Uploading s3://{bucket_name}/{key}")
            s3.upload_file(
                Filename=str(file_path),
                Bucket=bucket_name,
                Key=key,
                ExtraArgs={
                    "Metadata": {
                        "hf_repo": args.repo,
                        "hf_revision": args.revision,
                        "sha256": sha256,
                    }
                },
            )
            uploaded += 1

        print(f"Done. planned={planned} uploaded={uploaded} skipped={skipped} dry_run={args.dry_run}")

    # snapshot_download may return a path in the global HF cache; we won't delete it.
    # If user provided --local-dir, they control lifecycle of that folder.
    if args.local_dir and not args.keep_local and not args.dry_run:
        # Safe deletion only of the explicit local_dir (not HF cache).
        try:
            import shutil

            shutil.rmtree(args.local_dir, ignore_errors=True)
            print(f"Cleaned local-dir: {args.local_dir}")
        except Exception as e:
            print(f"WARN: Failed to clean local-dir '{args.local_dir}': {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
