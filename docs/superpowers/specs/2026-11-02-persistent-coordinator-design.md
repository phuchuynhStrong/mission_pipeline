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

**Success test:** every question a tool sends to the coordinator gets an answer, also across a crash,
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
| `ask` from a plain terminal fails: `dispatch_inactive: ask requires an active supervised Dispatch` | VERIFIED | live test L1, 2026-11-02 |
| `send --to run:<id> --type question` from a plain terminal works; the coordinator sees `from` = sender's terminal handle | VERIFIED | live test L1 |
| `reply --id <msg>` delivers a `status` message, subject `Re: <subject>`, to the sender's terminal mailbox; the sender reads it with a plain `check` | VERIFIED | live test L1 |
| An outside `question` is consumed by the first `check` (plain, `--run`, or `--wait`); a second check returns nothing; no Delivery id is shown | VERIFIED | live test L2 |
| A consumed message stays in `orchestration inbox` with `to: run:<id>` and `handled: true` | VERIFIED | live test L2 |
| `inbox` has `--limit` only: no recipient filter, no paging | VERIFIED | `orca orchestration inbox --help` |
| The shared Run id is saved in `~/.claude/pipeline/coordinator.json`; Binding rejoins it | VERIFIED | `SKILL.md:56`, `:73-82` |
| A bound Run replays the same Delivery until `--ack` or all its messages are marked read | VERIFIED (help text); **not seen for outside `send` messages** (L2) | `orca orchestration check --help` |
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
| A worker of one Run cannot `send` to another Run: `dispatch_run_mismatch` | VERIFIED | live test L1b |
| Whether a reply carries any id linking it to the question (only `Re: <subject>` was seen) | UNKNOWN | — |
| What happens to a reply when the sender's terminal closes before it reads it | UNKNOWN | — |
| Input typed by `terminal send` during a turn is queued and handled after the turn | VERIFIED (one run) | live test L3 |
| Fencing shows as `run-current --from <handle>` → `runId: null`; a permission prompt shows in `terminal read --screen` | VERIFIED | live tests L4, L6 |
| Prefix rules like `Bash(orca status:*)` match; deny rules block; off-list prompts. Matching of `${CLAUDE_PLUGIN_ROOT}`, `$(...)` and redirects was not tested | VERIFIED / UNKNOWN | live test L6 |
| A `SessionStart` hook with matcher `compact` runs after a manual `/compact` (automatic compact not tested) | VERIFIED / INFERRED | live test L7 |

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

`ask` only works from inside a supervised Dispatch (L1), so outside tools use `send`. A
session that is itself a worker of another Run cannot send to the shared Run
(`dispatch_run_mismatch`, L1b); only plain terminals (tools, your own Claude sessions) can.

| | `send` question (main channel) | `terminal send` (escape hatch) |
|---|---|---|
| Command | `orca orchestration send --to run:<shared> --type question --subject "<tag> <title>" --body "<text>"` | `orca terminal send --terminal <coordinator> --text … --enter` |
| Use for | everything that must arrive: status, details, start, stop, decisions, any request | anything else a human would type; never for a message that must arrive |
| Coordinator down | kept in the Run until read | not replayed |
| Answer | `reply` → `status` message in the sender's terminal mailbox, subject `Re: <subject>` | screen text, read with `terminal read` |

- Tools find `<shared>` with `python3 -I <plugin root>/scripts/state.py run` (full path, so
  it works from any repo).
- The tool waits for the answer with `orca orchestration check --wait --timeout-ms <n>
  --json` in its own terminal and matches it by subject.
- **Tag (my call):** the subject starts with a unique tag the tool picks (e.g. `[t-<random>]`),
  because no reply-to id was seen (UNKNOWN). The coordinator keeps the subject in its reply.
- A tool that times out waits again with `check --wait`. It never sends the question again,
  because the coordinator would act twice.
- The sender must stay in a live Orca terminal until it reads the answer (what happens to a
  reply for a closed terminal is UNKNOWN).

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
- **Orca does not replay an outside question** (L2): the first `check` consumes it. So the
  handled log is the main safety, and a crash after `check` but before `started` would lose
  the message. **Inbox scan** closes that gap: at Binding and after every wake, before the
  wait is re-armed, read `orca orchestration inbox --limit <n> --json`, keep rows with
  `to: run:<shared>` and `type: question`, and treat each one with no `answered` line as a
  new message (routing from step 1). `inbox` has no recipient filter or paging, so `<n>`
  must cover the busiest gap between scans; the value and what to do when the oldest row is
  still unhandled are left to the builder.
- **Recovery** (routing step 2, and at Binding for every `started` line with no `answered`):
  check whether the action happened (e.g. `state.py show`).
  - Done → reply with the result, write `answered`.
  - Not done → do it now, reply, write `answered`.
  - Cannot tell (free-text action with no trace) → reply "I may have done this before a
    restart; check <what>", write `answered`.
- A crash between `reply` and `answered` can send a second answer (accepted).
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
- **Writes under `~/.claude/pipeline` prompt** with the Write tool, even with
  `additionalDirectories` (L6). So the coordinator never uses Write or Edit there: every
  file it writes (`mission.md`, notes, notices, handled log) goes through `state.py` or a
  plugin script, which the allowlist covers (my call). Workers keep writing their own
  reports; whether they hit the same prompt is left to the builder to check.

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
2. Handle is live but not working → do **not** launch. "Not working" is any of:
   `orca orchestration run-current --from <handle>` is not the shared Run (fenced, L4);
   `terminal read --screen` shows a permission prompt ("Do you want to proceed?", "Do you
   want to create", L6); `heartbeat` older than 20 min (15 min wait + grace). Do not
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
| First time (cutover) | The user, by hand | No mission has a live worker; the user answers the one-time folder trust dialog (L6); its Binding fences the old session, which the user then closes |
| Terminal gone (crash, closed, Claude exited) | Watchdog | Saved handle not in `orca terminal list`, no launch in the last 10 min |
| After a reboot | Watchdog (launchd at login, after `orca open`) | Same as the row above |
| Terminal live but not waiting (fenced, prompt, Binding failed) | Nobody | Notice on the board; the user fixes it |
| Two launches in a row failed | Nobody | Notice; watchdog pauses until the user clears it |

The launch inherits accept-edits mode and the allowlist from the workspace's
`.claude/settings.json` (`permissions.defaultMode: "acceptEdits"`; VERIFIED, L6). Nothing
is typed into a coordinator terminal until its screen shows the idle prompt, because text
typed during startup once replaced the launch prompt (L3).

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
| L1 | **Done 2026-11-02.** `ask` fails outside a Dispatch; `send` + `reply` work | §3 channel changed to `send` |
| L1b | **Done.** A worker of Run A sending `--to run:<B>` is refused: `dispatch_run_mismatch` | Only plain terminals reach the coordinator; workers of other Runs cannot (§3) |
| L2 | **Done 2026-11-02.** No replay of outside questions; consumed rows stay in `inbox` | §4 inbox scan added |
| L3 | **Done.** Text typed while a turn runs waits and is handled after the turn; it does not interrupt. Once, text typed while Claude was still starting replaced the launch prompt (cause INFERRED) | §1 launch waits for idle before anything is typed |
| L4 | **Done.** After another terminal binds the Run, `run-current --from <old handle>` returns `runId: null` | §9 detects fencing directly |
| L5 | **Done (part).** An automation with `* * * * *` ran its precheck every minute (`skipped_precheck`). The quit-Orca part was skipped (it would close every terminal) | automation works while Orca runs; reboot case stays UNKNOWN, launchd still preferred |
| L6 | **Done.** Project `defaultMode: acceptEdits` applied; allow rules ran with no prompt; deny rule blocked; an off-list command prompted, and the prompt text is visible with `terminal read --screen`. A first launch in a new folder shows a trust dialog. A Write-tool file in `~/.claude/pipeline` **prompted** even with `additionalDirectories` | §5 writes go through scripts; §1 first launch by hand; §9 reads the screen |
| L7 | **Done.** A `SessionStart` hook with matcher `compact` put its text into context after `/compact` | §5 notes hook confirmed |

All eight ran on 2026-11-02 on throwaway Runs (`run_ff9f6fa85f6f`, `run_5c14faff8cc1`); the
shared Run was not touched. L1 and L2 went against the first draft; the user approved the
`send` channel and the inbox scan. The test automation and terminals were removed.

## Cutover (my call)

Start the dedicated coordinator only when no open mission has a live worker. Its first
Binding fences the old daily-repo session and re-arms watchers (§10); close the old
session after.

## Left to the builder

- `state.py` subcommand names, handled-log prune rule, plugin script names and split.
- Exact text of the `reply` bodies and notices.
- Board wording for notices and the health line.
