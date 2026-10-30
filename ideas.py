# The team's own post ideas: one markdown note each, in ideas/.
#
# Every idea comes in through the Slack bot, which saves it here. A note
# looks like:
#
#   ---
#   status: new
#   captured: 2026-09-22T15:04:11+00:00
#   via: slack
#   link: https://example.com/article
#   shortlisted: []
#   buffer_id:
#   ---
#   Agencies should fear AI ads more than brands do.
#
#   ## Interview
#   ...
#
# status is one of: new · shortlisted · drafted · skipped · archived. new and
# shortlisted ideas are open, and go into Sunday's shortlist. A note with no
# status (one written straight into ideas/ rather than sent to the bot) is
# left out.

import re
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).parent
IDEAS_DIR = HERE / "ideas"

OPEN = {"new", "shortlisted"}

URL = re.compile(r"https?://\S+")


def plain(value):
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def read(path):
    """An idea note as {"path", "meta", "body"}."""
    text = path.read_text()
    meta, body = {}, text
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        body = match.group(2)
    # Hand-edited notes may have unquoted dates, which YAML reads as date objects.
    meta = {k: plain(v) for k, v in meta.items()}
    meta.setdefault("shortlisted", [])
    return {"path": path.relative_to(HERE).as_posix(), "meta": meta, "body": body.strip()}


def write(idea):
    front = yaml.safe_dump(idea["meta"], sort_keys=False, allow_unicode=True).strip()
    (HERE / idea["path"]).write_text(f"---\n{front}\n---\n{idea['body'].strip()}\n")


def load(path):
    return read(HERE / path)


def open_ideas():
    """Every idea still waiting for a post, oldest first."""
    if not IDEAS_DIR.exists():
        return []
    ideas = [read(p) for p in sorted(IDEAS_DIR.glob("*.md"))]
    ideas = [i for i in ideas if i["meta"].get("status") in OPEN]
    return sorted(ideas, key=lambda i: str(i["meta"].get("captured", "")))


def raw_text(idea):
    """What was captured, without the interview appended below it."""
    return idea["body"].split("\n## Interview", 1)[0].strip()


def slug(text):
    words = re.sub(r"[^a-z0-9 ]", "", URL.sub("", text).lower()).split()
    return "-".join(words[:8]) or "idea"


def capture(text, via, now=None):
    """Save a new idea note and return it. Keeps the words exactly as sent."""
    now = now or datetime.now(timezone.utc)
    link = URL.search(text)
    IDEAS_DIR.mkdir(exist_ok=True)
    path = IDEAS_DIR / f"{now:%Y-%m-%d} {slug(text)}.md"
    n = 2
    while path.exists():
        path = IDEAS_DIR / f"{now:%Y-%m-%d} {slug(text)} {n}.md"
        n += 1
    idea = {
        "path": path.relative_to(HERE).as_posix(),
        "meta": {
            "status": "new",
            "captured": now.isoformat(timespec="seconds"),
            "via": via,
            "link": link.group(0).rstrip(".,)") if link else None,
            "shortlisted": [],
            "buffer_id": None,
        },
        "body": text.strip(),
    }
    write(idea)
    return idea


def set_status(path, status, **fields):
    idea = load(path)
    idea["meta"]["status"] = status
    idea["meta"].update(fields)
    write(idea)


def mark_shortlisted(path, week):
    idea = load(path)
    if idea["meta"]["status"] == "new":
        idea["meta"]["status"] = "shortlisted"
    if week not in idea["meta"]["shortlisted"]:
        idea["meta"]["shortlisted"].append(week)
    write(idea)


def save_interview(path, turns):
    """Write the interview under the idea, replacing any earlier copy of it."""
    idea = load(path)
    lines = ["## Interview", ""]
    for turn in turns:
        lines.append(f"**Q:** {turn['question']}")
        lines.append("")
        if turn.get("answer"):
            lines.append(f"**A:** {turn['answer']}")
            lines.append("")
    idea["body"] = raw_text(idea) + "\n\n" + "\n".join(lines)
    write(idea)
