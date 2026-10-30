# Puts a rendered graphic somewhere public, so Buffer can fetch it.
#
# Buffer takes media from a URL, not an upload. The graphics go to a
# Cloudflare R2 bucket with public access on, using R2's S3-compatible API.
# Needs these environment variables (repo secrets for the workflows):
#   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET,
#   R2_PUBLIC_URL (the bucket's public address, like https://pub-xxxx.r2.dev)

import os
from pathlib import Path

import boto3

NEEDED = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_URL"]


def configured():
    return all(os.environ.get(name) for name in NEEDED)


def upload(path, content_type="video/mp4"):
    """Upload the file and return its public URL."""
    missing = [name for name in NEEDED if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"R2 isn't set up: missing {', '.join(missing)}")
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    key = f"graphics/{Path(path).name}"
    client.upload_file(str(path), os.environ["R2_BUCKET"], key, ExtraArgs={"ContentType": content_type})
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"
