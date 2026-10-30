// The go-between for Slack and GitHub.
//
// Slack calls this whenever someone presses a button or writes in the channel.
// It checks the call really came from Slack and from the configured channel,
// acknowledges it straight away, and starts the `slack` workflow in the
// content-machine repo, which does the actual work (handle.py) and replies in
// the channel.
//
// It also starts `gather` and `shortlist` on a schedule (the crons in
// wrangler.toml). GitHub's own schedules can start hours late; these don't.
//
// Secrets (set with `wrangler secret put`):
//   SLACK_SIGNING_SECRET  from the Slack app's Basic Information page
//   SLACK_BOT_TOKEN       the bot token (xoxb-...) from OAuth & Permissions
//   SLACK_CHANNEL_ID      the channel the bot works in (C...); everything else is ignored
//   GITHUB_TOKEN          fine-grained token for your copy of this repo, Contents: read and write
//   GITHUB_REPO           your repo as owner/name, e.g. your-org/content-machine
//
// Point both the Slack app's Event Subscriptions and Interactivity request URLs
// at this Worker's URL.

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Not found", { status: 404 });
    }

    // Anyone can find a Worker's URL; only Slack can sign the request.
    const body = await request.text();
    if (!(await validSignature(request, body, env.SLACK_SIGNING_SECRET))) {
      return new Response("Forbidden", { status: 403 });
    }

    const type = request.headers.get("Content-Type") ?? "";

    // Button presses arrive form-encoded, with the details in a `payload` field.
    if (type.includes("application/x-www-form-urlencoded")) {
      const payload = JSON.parse(new URLSearchParams(body).get("payload") ?? "{}");
      ctx.waitUntil(handleInteraction(payload, env).catch((error) => console.error(error)));
      return new Response("");
    }

    const event = JSON.parse(body);

    // Slack checks the URL once, when it's saved in the app settings.
    if (event.type === "url_verification") {
      return new Response(JSON.stringify({ challenge: event.challenge }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // Slack resends an event it thinks was missed. The first delivery is
    // already being handled, so a retry would repeat the work.
    if (request.headers.get("X-Slack-Retry-Num")) {
      return new Response("ok");
    }

    // Always answer within three seconds, or Slack retries. The work carries
    // on after the response.
    if (event.type === "event_callback") {
      ctx.waitUntil(handleEvent(event.event, env).catch((error) => console.error(error)));
    }
    return new Response("ok");
  },

  async scheduled(controller, env) {
    const workflow = SCHEDULE[controller.cron];
    if (!workflow) throw new Error(`No workflow for cron ${controller.cron}`);
    try {
      await dispatch(env, workflow);
    } catch (error) {
      await slack(env, "chat.postMessage", {
        channel: env.SLACK_CHANNEL_ID,
        text: `Couldn't start the ${workflow} workflow on GitHub. Run it from the Actions tab. ${error.message.slice(0, 200)}`,
      });
      throw error;
    }
  },
};

// Each cron in wrangler.toml and the workflow it starts. Times are UTC.
const SCHEDULE = {
  "0 13 * * *": "gather", // daily
  "0 14 * * SUN": "shortlist", // Sundays, an hour after gather
};

// Slack signs each request: HMAC-SHA256 of "v0:<timestamp>:<body>". A request
// older than five minutes is refused, so a captured one can't be replayed.
async function validSignature(request, body, secret) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp");
  const signature = request.headers.get("X-Slack-Signature");
  if (!secret || !timestamp || !signature) return false;
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v0:${timestamp}:${body}`));
  const expected = "v0=" + [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return expected.length === signature.length && timingSafeEqual(expected, signature);
}

function timingSafeEqual(a, b) {
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

// A button press: "draft" or "interview" on a pick. A done label isn't a real
// button, so nothing else arrives here.
async function handleInteraction(payload, env) {
  if (payload.type !== "block_actions" || payload.channel?.id !== env.SLACK_CHANNEL_ID) return;

  const [action, date, number] = (payload.actions?.[0]?.value ?? "").split(":");
  if (action !== "draft" && action !== "interview") return;

  // Say something straight away, in the pick's thread, so the press doesn't
  // look ignored while the workflow starts.
  await slack(env, "chat.postMessage", {
    channel: env.SLACK_CHANNEL_ID,
    thread_ts: payload.message?.ts,
    text: action === "draft" ? `Drafting #${number}…` : `Starting the interview on #${number}…`,
  });
  await dispatchOrSay(env, { kind: "tap", action, date, number: Number(number) });
}

// A message in the channel. The bot's own messages and edits are ignored.
async function handleEvent(event, env) {
  if (event.type !== "message" || event.subtype || event.bot_id) return;
  if (event.channel !== env.SLACK_CHANNEL_ID || !event.text) return;

  // An 👀 reaction says "got it" without another message; the reply follows.
  await slack(env, "reactions.add", { channel: event.channel, timestamp: event.ts, name: "eyes" });

  await dispatchOrSay(env, {
    kind: "text",
    text: event.text,
    // A reply in a thread points at the message that started it: the pick, or
    // the interview question, being answered.
    thread_ts: event.thread_ts && event.thread_ts !== event.ts ? event.thread_ts : null,
  });
}

// If GitHub won't start the workflow, say so in the channel. Otherwise a
// press shows "Drafting…" and then nothing ever happens.
async function dispatchOrSay(env, payload) {
  try {
    await dispatch(env, "slack", payload);
  } catch (error) {
    await slack(env, "chat.postMessage", {
      channel: env.SLACK_CHANNEL_ID,
      text: `Couldn't start the drafting workflow on GitHub. ${error.message.slice(0, 200)}`,
    });
    throw error;
  }
}

async function slack(env, method, params) {
  const response = await fetch(`https://slack.com/api/${method}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      Authorization: `Bearer ${env.SLACK_BOT_TOKEN}`,
    },
    body: JSON.stringify(params),
  });
  return response.json();
}

// Starts a workflow in the repo (a repository_dispatch event of that name).
async function dispatch(env, eventType, payload = {}) {
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "content-machine-worker",
    },
    body: JSON.stringify({ event_type: eventType, client_payload: payload }),
  });
  if (!response.ok) {
    throw new Error(`GitHub dispatch failed: ${response.status} ${await response.text()}`);
  }
}
