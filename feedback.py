# The team's verdicts on shortlist picks, and how the next shortlist learns from them.
#
# Two kinds of signal go into verdicts.json:
#   - what the team says in Slack ("skip 5, layoffs", "angle's off on 2"), which
#     handle.py records with their note;
#   - drafting a pick, which counts as a thumbs-up.
# A pick the team never drafted and never commented on is a weak "no", worked out
# when the next shortlist is picked rather than stored.
#
# The rules live in voice/selection.md. These are the examples, which do more
# work than rules. Now and then, patterns here are worth turning into a rule
# there (by hand).

import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
VERDICTS_FILE = HERE / "verdicts.json"
SHORTLISTS_DIR = HERE / "shortlists"

# How many recent verdicts the shortlist sees. Enough to show the team's taste
# without old weeks drowning out recent ones.
RECENT = 40

LABELS = {
    "good": "Good pick",
    "drafted": "Good pick (drafted it)",
    "skip": "Skip",
    "angle_off": "Right story, wrong angle",
}


def load():
    if not VERDICTS_FILE.exists():
        return []
    return json.loads(VERDICTS_FILE.read_text())


def record(date, pick, verdict, note=""):
    """Add a verdict on one pick. A later verdict on the same pick sits alongside the earlier one."""
    verdicts = load()
    verdicts.append({
        "week": date,
        "number": pick["number"],
        "headline": pick["headline"],
        "angle": pick["angle"],
        "verdict": verdict,
        "note": note,
        "recorded": datetime.now(timezone.utc).isoformat(),
    })
    VERDICTS_FILE.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False) + "\n")


def undrafted(verdicts):
    """Past picks the team neither drafted nor commented on."""
    judged = {(v["week"], v["number"]) for v in verdicts}
    quiet = []
    for path in sorted(SHORTLISTS_DIR.glob("*.json")):
        saved = json.loads(path.read_text())
        for pick in saved["picks"]:
            if not pick["buffer_id"] and (saved["date"], pick["number"]) not in judged:
                quiet.append((saved["date"], pick))
    return quiet


def examples():
    """The team's recent verdicts, written out for the shortlist prompt. "" if there are none."""
    verdicts = load()
    lines = []
    for v in verdicts[-RECENT:]:
        line = f"- [{v['week']}] {v['headline']}. Angle: {v['angle']}\n  Verdict: {LABELS[v['verdict']]}"
        if v["note"]:
            line += f". Team note: {v['note']}"
        lines.append(line)
    for week, pick in undrafted(verdicts)[-RECENT:]:
        lines.append(f"- [{week}] {pick['headline']}\n  Verdict: Not drafted, no comment (a weak no)")
    if not lines:
        return ""
    return "<team_recent_verdicts>\n" + "\n".join(lines) + "\n</team_recent_verdicts>"
