# Persistent coordinator — design

Date: 2026-11-02. Status: draft, waiting for user review. Builder check and hawkeye review
done; fixes applied.

## Problem

Today the coordinator is a Claude Code session the user opens in their daily repo
(`skills/pipeline/SKILL.md`). Other AI tools and other Claude sessions now control the
pipeline and chat with the coordinator through Orca, addressed by the coordinator's
terminal handle. When that session closes, the tools have nothing to talk to, and a new
session starts with no memory of the chat.

## Goal

One coordinator that is always reachable. The user, other AI tools and other Claude
sessions talk to it back and forth, like a chat. It runs every mission on this machine.

**Success test:** every `ask` sent to the coordinator gets an answer, also across a crash,
a restart or a `/compact`. A duplicate answer after a crash is accepted; a missing one is not.

## Anti-goal

The design fails if the coordinator misses or loses a message from a tool, even when every
part works on its own (user, 2026-11-02).

## Non-goals

- Two coordinator sessions live at once (unchanged from the shared-run design, 2026-10-14).
- A permission layer for outside tools. Local tools already have full control through
  `orca terminal send`, so a confirmation step would protect nothing (user decision).
- Cloud or remote hosting. The coordinator runs on this Mac.

## Facts this design rests on

| Fact | Label | Source |
|---|---|---|
| The shared Run id is saved in `~/.claude/pipeline/coordinator.json`; Binding rejoins it | VERIFIED | `SKILL.md:56`, `:73-82` |
| `ask` blocks until answered; on timeout the question stays pending; `--resume <message_id>` waits again; max 30 min per wait | VERIFIED | `orca orchestration ask --help` |
| `ask --to run:<id>` addresses a Run, not a terminal | VERIFIED (usage line only; the flag has no description) | `orca orchestration ask --help` |
| `ask` has `--dispatch-capability`; from an active Dispatch a message defaults to its own Run | VERIFIED | `orca orchestration ask --help`, `send --help` |
| The coordinator answers with `orchestration reply --id <msg_id> --body <text>` | VERIFIED | `orca orchestration reply --help` |
| A bound Run replays the same Delivery until `--ack` **or all its messages are marked read** | VERIFIED | `orca orchestration check --help` |
| `terminal send` needs a live terminal; it returns a "queued/input-accepted receipt", but nothing replays a message the session never handled | VERIFIED (live terminal, receipt), INFERRED (no replay) | `orca --help`; `orca terminal send --help` |
| `orca agent launch --surface terminal` always runs the agent CLI in a terminal, whatever the Chat UI setting | VERIFIED | `orca agent launch --help` |
| A message with no mission owner is dropped today ("take no action") | VERIFIED | `SKILL.md:276-282` |
| Worker `question`s get "Decide yourself…", except the senior relaying a user request | VERIFIED | `SKILL.md:322-327` |
| A second session that binds the Run fences the coordinator (`consumer_fenced`) | VERIFIED | `SKILL.md:305-307` |
| The wait is not re-armed when no mission has a live worker ("Unarmed gap"); Binding runs only when a worker is live | VERIFIED | `SKILL.md:73-74`, `:299-304` |
| Reader, senior and planner all run with `--worktree current` | VERIFIED | `SKILL.md:21-23`; `references/orca-commands.md:20-23` |
| `--worktree path:` needs a registered Orca repo | VERIFIED | `references/orca-commands.md:103-104` |
| Greptile delay and merge watcher are background Bash in the coordinator session | VERIFIED | `SKILL.md:143-145`; `references/orca-commands.md:84-96` |
| Mission state is keyed by repo folder and id (`<slug>/<id>.json`) | VERIFIED | `scripts/state.py:37-38` |
| `state.py list` and the board read only `*.json` inside sub-folders of `~/.claude/pipeline` | VERIFIED | `scripts/state.py` `cmd_list`; `hooks/register.tsx:333-335` |
| `run-use` from a new terminal takes over a live Run; unacked messages replay under a new Delivery id | VERIFIED | shared-run design, T1 step 2 |
| Orca automations take a cron trigger, a `--precheck` command and `--reuse-session` | VERIFIED | `orca automations create --help` |
| Payload of an `ask` from a plain terminal, and from inside another Run's Dispatch | UNKNOWN | live tests L1, L1b |
| Whether `reply` marks a question read (which ends its replay) | UNKNOWN | live test L2 |
| Whether a `reply` sent after the asker stopped waiting reaches a later `--resume` | UNKNOWN | live test L2 |
| How Claude Code orders input typed by `terminal send` while a turn is running | UNKNOWN | live test L3 |
| Whether an outside process can see that the coordinator is fenced or at a permission prompt | UNKNOWN | live tests L4, L6 |
| How Claude Code permission rules match subcommands, `${CLAUDE_PLUGIN_ROOT}`, `$(...)` and redirects | UNKNOWN | live test L6 |
| A `SessionStart` hook with matcher `compact` runs after an automatic or manual compact | INFERRED | live test L7 |

## Design

### 1. Where it lives (user decision)

- One long-lived Claude Code session in a **dedicated Orca terminal**, in its own workspace,
  apart from the user's daily repo.
- It is the only consumer of the shared Run. No other session ever runs `run-use` or
  `run-create` for it.
- Started with `orca agent launch --agent claude --surface terminal --worktree path:<ws>
  --prompt "/pipeline"`.
- **`/pipeline` with no arguments** (new): run Binding, re-arm watchers (§10), recover open
  asks (§4), arm the wait, reply with status. No mission is created.
- At Binding the session saves its terminal handle in `coordinator.json` (new field
  `terminal`, via `state.py run`).

### 2. The wait is always armed (changes `SKILL.md` Waiting)

- Binding runs on **every session start**, not only when a worker is live.
- The wait is re-armed after every wake and every timeout. The "Unarmed gap" rule
  (`SKILL.md:302-304`) is removed.
- "Before any turn ends, a wait is running" applies always, not only "while any open mission
  has a live worker" (`SKILL.md:299-301`).
- Each time the wait is armed, the session writes `~/.claude/pipeline/heartbeat` (time and
  terminal handle). The watchdog reads it (§9).
- Cost (accepted): an idle coordinator wakes every 15 min (`SKILL.md:270`), and every three
  empty wakes it runs `worker-list` (`SKILL.md:308-311`). My call: when no mission is open,
  skip the `worker-list` step.

### 3. Channels

| | `ask` (main channel) | `terminal send` (escape hatch) |
|---|---|---|
| Command | `orca orchestration ask --to run:<shared> --question "<text>"` | `orca terminal send --terminal <coordinator> --text … --enter` |
| Use for | everything that must arrive: status, details, start, stop, decisions, any request | anything else a human would type; never for a message that must arrive |
| Coordinator down | waits in the Run | not replayed |
| Answer | `reply` to the asker | screen text, read with `terminal read` |

Tools find `<shared>` with `python3 -I <plugin root>/scripts/state.py run` (full path, so it
works from any repo). They resume a timed-out `ask` with `--resume <message_id>`, never by
sending a new question.

### 4. Routing and the handled log

**Routing**, for each message in a batch, in this order:

1. Message id has an `answered` line in the handled log → skip it.
2. Message id has a `started` line but no `answered` → **recovery** (below).
3. Payload missing or not JSON: type `question` → outside ask; any other type → notice (§6).
4. Payload has a `dispatchId` and `state.py owner` exits 0 → the current mission rules
   (unchanged).
5. Type `question`, and either no `dispatchId` or `owner` exits 3 → **outside ask**. (An ask
   from a session that is itself a worker in another Run carries that Run's `dispatchId`,
   INFERRED; L1b checks.)
6. Anything else (other types with no owner, `owner` exit 4 or other codes) → notice (§6),
   no action.

**Outside ask:** do what it asks, as if the user typed it, then `orchestration reply`.

- Every ask is answered **in the same wake, before the ack**. A long request ("start X and
  tell me when the spec is done") gets an immediate reply ("started X; ask for status") and
  is never held open.
- Predefined actions (user): status of all missions, details of one mission, start a
  mission (same as `/pipeline <args>`), stop a mission (Abort, `SKILL.md:181`). Any other
  request is handled like a request the user types.
- My call: the question is free text; the coordinator reads it. No fixed command grammar.
- Never answered with "Decide yourself…"; that stays for mission workers only.

**Handled log:** `~/.claude/pipeline/handled.jsonl`, one line per event:
`{"msg_id", "delivery_id", "from", "kind", "status": "started|answered", "at", "summary"}`.
Written only through `state.py` (new subcommands; names left to the builder).

- Order for every outside ask: write `started` → act → `reply` → write `answered` → ack the
  batch (the ack stays last, `SKILL.md:284`).
- **Recovery** (routing step 2, and at Binding for every `started` line with no `answered`,
  because a `reply` may have marked the message read and ended its replay, L2): check
  whether the action happened (e.g. `state.py show`).
  - Done → reply with the result, write `answered`.
  - Not done → do it now, reply, write `answered`.
  - Cannot tell (free-text action with no trace) → reply "I may have done this before a
    restart; check <what>", write `answered`.
- A crash between `reply` and `answered` can send a second answer (accepted). If L2 shows
  `reply --retry-request <msg id>` makes the second reply a no-op, use it.
- Prune rule for old lines: left to the builder.

### 5. Memory

- **Normal path (user decision):** the user opens the coordinator terminal and runs
  `/compact` when they choose, with instructions to keep pending decisions and recent
  answers.
- **Safety net (my call):** when an outside ask leads to a decision or a pending item, the
  coordinator appends it to `~/.claude/pipeline/coordinator-notes.md` in the same step that
  writes `answered`. Notes are re-read at Binding, and after any compact through a
  `SessionStart` hook with matcher `compact` that prints the notes into context (INFERRED;
  L7). A normal turn never reads them.
- **Mission files:** `mission.md`, readings, review reports, `pr-body.md`, its split files,
  `greptile-review.md`, `pr.json`, `pr-final.json` move from `<scratchpad>/pipeline/<id>/`
  (`SKILL.md:51-55`) to `~/.claude/pipeline/files/<repo-basename>/<id>/`. The scratchpad is
  per session and is gone after a restart. The `pr-final.json` path in
  `references/orca-commands.md:93` moves too.
- `inbox.json` stays in the session's scratchpad. An unacked batch replays after a restart,
  and a shared file would let a fenced old session overwrite the new session's batch.
- `~/.claude/pipeline` is outside the dedicated workspace, so it goes in the workspace's
  `additionalDirectories` (INFERRED that acceptEdits needs this; L6).

### 6. Notices

Every "tell the user" in the skill now reaches a terminal nobody watches. So each one is
also written to `~/.claude/pipeline/notices.jsonl` (`at`, `kind`, `mission`, `line`,
`cleared`). This covers dropped messages (§4 routing 3 and 6), Binding failures,
`consumer_fenced`, Linear errors, and kept worktrees.

- The board (`/pboard`) shows open notices above the mission rows.
- Every status reply lists open notices.
- A notice is cleared by an ask or a user message that says so.

### 7. Target repo (user decision)

Every mission names its repo, by path or Orca repo selector, in `/pipeline` or in the
"start a mission" ask. The coordinator's own folder is never assumed to be the target.

- A start request with no repo, or a repo not in `orca repo list --json`, gets a reply
  asking for a registered repo; no mission is created.
- Stored at `state.py new` (`--repo`, already there, `SKILL.md:193`).
- Used by every step that today relies on the working folder:
  - reader, senior and planner `--worktree path:<repo>` instead of `current`
    (`SKILL.md:21-23`, `:84`; `references/orca-commands.md:20-23`)
  - spec, plan and plan-mode paths and commits (`SKILL.md:57-59`, P1)
  - `owner_repo` (`SKILL.md:50`)
  - `orca worktree create --repo <selector> --no-parent` (`SKILL.md:61`, step 5); my call to
    add `--no-parent` so the worktree is not a child of the coordinator's workspace.

### 8. Decisions from outside asks (user decision)

Any tool can give "the user's word" with a later ask: `NEEDS_USER` (reviewer, Greptile),
fix or decline, implementer `failed`, `escalation`, an existing plan-mode folder, Abort.
The coordinator acts on it exactly as on the user's chat reply.

- A status reply lists every pending decision: mission id, `attention.reason`, and the
  report path the decider needs (e.g. `review.md`, `greptile-review.md`). Tools learn a
  decision is due only by asking for status; there is no push.
- **Senior brainstorm is different:** it is a conversation in the senior's own terminal,
  not with the coordinator. A tool joins through `terminal send` / `terminal read` on the
  senior's handle (§3: not replayed). My call: the status reply gives the senior's handle;
  the coordinator does not relay a brainstorm.

### 9. Watchdog (my call; mechanism open)

Runs every minute.

1. Saved handle in `coordinator.json` is not in `orca terminal list --json` → launch a new
   coordinator (§1 command). The new session's Binding takes over the Run; unacked messages
   replay.
2. Handle is live but `heartbeat` is older than 20 min (15 min wait + grace) → do **not**
   launch (a second session would fence the first, `SKILL.md:306`). Write a notice (§6):
   "coordinator not waiting: <handle>". This covers a Binding failure, `consumer_fenced`,
   Claude exited to the shell, and a stalled permission prompt.
3. **Launch lock:** no new launch within 10 min of the last one (time kept in
   `coordinator.json`). A second failed launch in a row → notice, stop launching until the
   user clears it.

- Mechanism: an Orca automation with `--precheck`, or a macOS launchd agent. Pick after L5.
- **After a reboot:** `orca` commands need a running Orca runtime (`orca --help`: "Most
  commands require a running Orca runtime"). An Orca automation probably cannot run while
  Orca is closed (UNKNOWN; L5 checks). A launchd agent can run `orca open` at login and
  then do the same checks, so the reboot case points to launchd.
- The Mac must be awake for any of this; how (e.g. `caffeinate`) is left to the user.

**When the coordinator starts:**

| Moment | Who starts it | Condition |
|---|---|---|
| First time (cutover) | The user, by hand | No mission has a live worker; its Binding fences the old session, which the user then closes |
| Terminal gone (crash, closed, Claude exited) | Watchdog | Saved handle not in `orca terminal list`, no launch in the last 10 min |
| After a reboot | Watchdog (launchd at login, after `orca open`) | Same as the row above |
| Terminal live but not waiting (fenced, prompt, Binding failed) | Nobody | Notice on the board; the user fixes it |
| Two launches in a row failed | Nobody | Notice; watchdog pauses until the user clears it |

The launch inherits accept-edits mode and the allowlist from the workspace's
`.claude/settings.json` (`permissions.defaultMode: "acceptEdits"`; INFERRED, L6 checks).

### 10. Watchers survive a restart

At Binding, for every open mission:

- stage `pr` with no Greptile reviewer started yet → if the PR is more than 5 min old, start
  the Greptile reviewer now; else arm the delay for the time left.
- stage `pr` or `ready` → re-arm the merge watcher.

This also covers the cutover: when the old daily-repo session closes, its watchers die and
the new session re-arms them.

### 11. Permissions (user decision; rules my call)

- The coordinator session runs in **accept edits** mode (`acceptEdits`) with an allowlist
  in the dedicated workspace's `.claude/settings.json`.
- An outside ask counts as the user's approval for a push, a PR and an outside API call
  (Linear, GitHub), the same way "run this mission" does today (`SKILL.md:145-147`).
- **Allowlist, narrow (my call).** Bare `orca`, `gh` or `git` would allow anything
  (`orca terminal send`, `orca agent launch`, `gh api`, `git -c alias…`), so:
  - one rule per `orca` subcommand the skill uses (`references/orca-commands.md`):
    `orca status`, `orca orchestration check|reply|run-current|run-show|run-use|run-create|
    worker-start|worker-show|worker-release|worker-stop|worker-abandon|worker-list`,
    `orca linear issue`, `orca linear status set`, `orca worktree create|rm`,
    `orca terminal close|rename`, `orca repo list`;
  - `gh pr create|list|view` only;
  - `python3 -I <plugin root>/scripts/state.py`;
  - **new plugin scripts** for everything else, each taking a mission id and touching only
    that mission's paths: git steps (branch, commit, push to the mission branch, `ls-files`
    checks), file moves and removes in the target repo (`SKILL.md:103-107`, `:245-247`,
    `:257-258`), the PR body split, the Greptile delay and the merge watcher
    (`references/orca-commands.md:84-96`). Script names and split: builder.
  - deny rules: `orca terminal send`, `orca automations`, `orca agent`, `gh api`,
    `git push --force`, `git push -f`.
- Anything off the list still prompts, and stalls the session until someone types in it.
  The watchdog's heartbeat check (§9 step 2) shows that on the board.

### 12. Changes outside the design doc

- `skills/pipeline/SKILL.md`: Binding, Waiting (§2), routing (§4), outside asks, decisions
  (§8), notices (§6), target repo (§7), watchers at Binding (§10), new places (§5), plugin
  scripts instead of raw git/rm/mv (§11), `/pipeline` with no arguments (§1), red flag
  "This ask has no owner, I'll skip it." → outside ask; answer it.
- `skills/pipeline/references/orca-commands.md`: `--worktree path:<repo>`, `--no-parent`,
  watcher paths, watchers as scripts.
- `skills/pipeline/references/roles.md`: any `{scratchpad}` path in a role template moves
  to `files/` (builder checks).
- `scripts/state.py`: `run` stores `terminal` and launch time; handled-log and notices
  subcommands.
- `hooks/register.tsx`: notices above the rows; coordinator health line from `heartbeat`.
- New: plugin scripts (§11), watchdog (§9), `SessionStart` compact hook (§5), workspace
  `.claude/settings.json` (§11).

## Accepted risk (user, 2026-11-02)

The coordinator reads Linear ticket text at intake (`SKILL.md:65`) and the readers and
reviewers read more untrusted text (tickets, PR comments). The user chose full trust for
local tools, but that does not cover ticket text. With auto-accepted edits and an allowlist
that includes push and PR, a malicious ticket could steer pushes and API calls. The narrow
allowlist (§11) limits what it can do; it does not remove the risk.

## Live tests to run first

| Id | Test | Decides |
|---|---|---|
| L1 | From a plain terminal (no Dispatch), `ask --to run:<shared>`; read the batch JSON | message type, where the msg id and sender sit, payload shape |
| L1b | Same, from a worker Dispatch of another Run | whether it carries a `dispatchId` (§4 routing 5) |
| L2 | `ask` with a short `--timeout-ms`, let it time out, coordinator `reply`, then `ask --resume`; then check whether the batch still replays after the `reply`; try `reply --retry-request` twice | late reply reaches asker; `reply` marks read; duplicate reply prevention |
| L3 | `terminal send` to the coordinator while it handles a wake | queue or interrupt; how strongly §3 must warn |
| L4 | Bind the Run from a second terminal; check the first terminal's heartbeat and `run-current --from <handle>` | whether fencing is visible from outside |
| L5 | Orca automation with a precheck that exits 0 when the saved handle is not live; also quit Orca and see whether the automation still runs | automation vs launchd |
| L6 | In the dedicated workspace with the §11 settings: run one command per rule, one off-list command, and writes into `~/.claude/pipeline`; from outside, `orca terminal show` / `terminal read --screen` | rule matching works; nothing needed prompts; a prompt is visible from outside |
| L7 | `SessionStart` hook with matcher `compact`; run `/compact` | notes come back after a compact |

All eight run before the plan is written. If L1, L1b or L2 comes out against this design
(no stable msg id, or a late reply is lost), the design goes back to the user; no fallback
is chosen in advance.

## Cutover (my call)

Start the dedicated coordinator only when no open mission has a live worker. Its first
Binding fences the old daily-repo session and re-arms watchers (§10); close the old
session after.

## Left to the builder

- `state.py` subcommand names, handled-log prune rule, plugin script names and split.
- Exact text of the `reply` bodies and notices.
- Board wording for notices and the health line.
