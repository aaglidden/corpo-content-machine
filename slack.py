# Talks to Slack: sends the weekly shortlist, interview questions and short
# replies to one channel.
#
# This file only sends. Button taps and replies come back the other way: Slack
# calls the Cloudflare Worker in worker/, which starts the `slack` workflow,
# which runs handle.py.

import os

import requests

import slots

API = "https://slack.com/api/{method}"

# Slack won't take more than 3000 characters in one block.
BLOCK_LIMIT = 2900


def call(method, **params):
    """Call a Slack Web API method with a JSON body and return the response."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set")
    response = requests.post(
        API.format(method=method),
        json=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {body.get('error')}")
    return body


def channel():
    channel_id = os.environ.get("SLACK_CHANNEL_ID")
    if not channel_id:
        raise RuntimeError("SLACK_CHANNEL_ID is not set")
    return channel_id


def blocks_for(text, buttons=None):
    """A message as Block Kit: the text, then a row of buttons.

    buttons is a list of (label, value). A button whose value is "noop" is a
    done label, not something to press, so it's shown as plain text.
    """
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:BLOCK_LIMIT]}}]
    actions = []
    for index, (label, value) in enumerate(buttons or []):
        if value == "noop":
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": label}]})
        else:
            actions.append({
                "type": "button",
                "action_id": f"button_{index}",
                "text": {"type": "plain_text", "text": label},
                "value": value,
            })
    if actions:
        blocks.append({"type": "actions", "elements": actions})
    return blocks


def send(text, buttons=None):
    """Send a message to the channel and return its ts, Slack's message ID.

    buttons, when given, is a list of (label, value): buttons in a row under
    the message. Pressing one sends its value back through the Worker.
    """
    params = {"channel": channel(), "text": text, "unfurl_links": False, "unfurl_media": False}
    if buttons:
        params["blocks"] = blocks_for(text, buttons)
    return call("chat.postMessage", **params)["ts"]


def send_video(path, caption):
    """Upload a rendered video to the channel, so the team can see it and attach it in Buffer."""
    size = os.path.getsize(path)
    name = os.path.basename(path)
    ticket = call("files.getUploadURLExternal", filename=name, length=size)
    with open(path, "rb") as video:
        upload = requests.post(ticket["upload_url"], data=video, timeout=120)
    if not upload.ok:
        raise RuntimeError(f"Slack upload failed: {upload.status_code}")
    call(
        "files.completeUploadExternal",
        files=[{"id": ticket["file_id"], "title": name}],
        channel_id=channel(),
        initial_comment=caption,
    )


def set_pick_buttons(pick, buttons):
    """Replace the buttons under a pick's message, e.g. once it's drafted."""
    text = pick_message(pick)
    call(
        "chat.update",
        channel=channel(),
        ts=pick["slack_ts"],
        text=text,
        blocks=blocks_for(text, buttons),
    )


def drafted_button(pick):
    """Swap a pick's buttons for a label saying it's done, so it can't be pressed twice."""
    set_pick_buttons(pick, [DONE_BUTTON])


def esc(text):
    """Escape text for Slack's mrkdwn, which treats & < > as control characters."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def is_idea(pick):
    """True when the pick is built on one of the team's own ideas."""
    return any(item.get("idea") for item in pick["items"])


def pick_message(pick):
    """One shortlist pick as a Slack message."""
    lines = [f"*{pick['number']}. {esc(pick['headline'])}*"]
    slot = slots.by_name(pick.get("slot"))
    if slot:
        lines.append(f":calendar: _{esc(slots.label(slot))}_")
    for item in pick["items"]:
        if item.get("idea"):
            lines.append(f":bulb: _Team idea ({esc(item['added'][:10])}):_ {esc(item['title'])}")
            if item["link"]:
                lines.append(f"   <{esc(item['link'])}>")
            continue
        title = esc(f"{item['title']} ({item['source']})")
        lines.append(f"• <{esc(item['link'])}|{title}>" if item["link"] else f"• {title}")
    lines.append("")
    lines.append(f"*Angle:* {esc(pick['angle'])}")
    for flag in pick["flags"]:
        lines.append(f":warning: {esc(flag)}")
    return "\n".join(lines)


DONE_BUTTON = (":white_check_mark: Drafted to Buffer", "noop")
INTERVIEWING_BUTTON = (":studio_microphone: Interview under way", "noop")
SKIPPED_BUTTON = ("Skipped", "noop")


def pick_buttons(date, pick):
    """Interview first for the team's own ideas, which are often one raw line;
    draft first for news, where the angle usually carries the post."""
    if pick["buffer_id"]:
        return [DONE_BUTTON]
    if pick.get("interview"):
        return [INTERVIEWING_BUTTON]
    draft = ("Just draft it" if is_idea(pick) else "Draft this", f"draft:{date}:{pick['number']}")
    interview = ("Interview us", f"interview:{date}:{pick['number']}")
    return [interview, draft] if is_idea(pick) else [draft, interview]


def send_shortlist(saved, item_count=None):
    """Send the week's picks, one message each, and record their message IDs.

    Recording the IDs is what lets a reply in a pick's thread ("angle this
    toward agencies") be matched back to that pick. Picks already in Buffer
    (when resending) get the done label instead of a button.
    """
    counted = f" from {item_count} items" if item_count else ""
    intro = (
        f"*This week's shortlist*: {len(saved['picks'])} picks{counted}, "
        "sorted into the week's slots.\n"
        "Press *Draft this* to send one to Buffer, or *Interview us* to talk it "
        "through first. Or reply in a pick's thread in your own words, like “draft this but angle it toward agencies”."
    )
    if saved.get("empty_slots"):
        intro += f"\nNothing strong enough for: {esc(', '.join(saved['empty_slots']))}."
    send(intro)
    for pick in saved["picks"]:
        pick["slack_ts"] = send(pick_message(pick), buttons=pick_buttons(saved["date"], pick))
