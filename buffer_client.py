# Creates a LinkedIn draft in Buffer.

import os

import requests
from dotenv import load_dotenv

# Reads the .env file next to this script and loads its lines into the
# environment, so os.environ.get("BUFFER_API_KEY") below can find the key.
# If there is no .env file (like on GitHub Actions later, where the key comes
# from a repo secret), this quietly does nothing.
load_dotenv()

# Buffer's GraphQL API lives at a single address; every request goes here.
BUFFER_API_URL = "https://api.buffer.com"

# The Buffer channel to draft to. Find the ID with Buffer's channel list
# (see the Buffer API docs) and set BUFFER_CHANNEL_ID.
LINKEDIN_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID", "")

# GraphQL is a way of asking an API for data. A "mutation" changes something
# (here: creates a post). $text and $channelId are placeholders that we fill
# in below, so we never paste values directly into the query string.
CREATE_DRAFT_MUTATION = """
mutation CreateDraft($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post { id status text }
    }
    ... on MutationError {
      message
    }
  }
}
"""


def create_draft(text, link_card=None, video_url=None):
    """Create a draft on the company's LinkedIn channel and return the post ID.

    link_card, when given, attaches a LinkedIn preview card for a URL. The
    card is separate from the post text, which is what lets the draft show
    a linked post as a preview without leaving a bare URL in the copy.

    video_url, when given, attaches a video from that public URL. A post
    carries one attachment, so use it instead of link_card, not with it.
    """
    # Read the API key from an environment variable so the secret never
    # appears in the code (and never gets committed to GitHub).
    api_key = os.environ.get("BUFFER_API_KEY")
    if not api_key:
        raise RuntimeError("BUFFER_API_KEY is not set")

    if not LINKEDIN_CHANNEL_ID:
        raise RuntimeError("BUFFER_CHANNEL_ID is not set")

    # These fields match what our test drafts used. saveToDraft=True is the
    # important one: it keeps the post as a draft so nothing publishes.
    post_input = {
        "channelId": LINKEDIN_CHANNEL_ID,
        "text": text,
        "saveToDraft": True,
        "mode": "addToQueue",
        "schedulingType": "automatic",
    }

    # Buffer nests network-specific options under metadata. Without an
    # explicit title/thumbnail Buffer falls back to showing the raw URL as
    # the card's title, which looks broken, so we always fill them in.
    if link_card:
        post_input["metadata"] = {"linkedin": {"linkAttachment": link_card}}

    if video_url:
        post_input["assets"] = [{"video": {"url": video_url}}]

    variables = {"input": post_input}

    # requests.post sends the query to Buffer. json= turns our Python
    # dictionary into JSON automatically. timeout stops us hanging forever.
    response = requests.post(
        BUFFER_API_URL,
        json={"query": CREATE_DRAFT_MUTATION, "variables": variables},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    # Raises an error if Buffer replied with an HTTP failure (401, 500, ...).
    response.raise_for_status()

    body = response.json()

    # GraphQL can return HTTP 200 and still contain errors, so check for them.
    if "errors" in body:
        raise RuntimeError(f"Buffer returned errors: {body['errors']}")

    result = body["data"]["createPost"]
    # A successful result has a "post"; a failed one only has a "message".
    if "post" not in result:
        raise RuntimeError(f"Buffer refused the draft: {result.get('message')}")

    return result["post"]["id"]


# This block only runs when you execute this file directly
# (python buffer_client.py), not when another file imports it.
if __name__ == "__main__":
    post_id = create_draft("content-machine connection test — safe to delete")
    print(f"Created draft {post_id}")
