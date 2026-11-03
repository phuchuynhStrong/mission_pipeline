# mission_pipeline

A Claude Code plugin. It ships the `pipeline` skill, the `/pboard` pane, and the
mission state script. One mission (a Linear ticket, a feature, a bug) runs through supervised
Orca workers: read > spec > plan > tree > build > review.

## Install

1. Install the Orca skills this plugin depends on. They ship with the Orca CLI and are
   version-matched to your Orca build, so they are not bundled here:

   ```
   orca skills install --skill orca-cli --skill orchestration --skill linear-tickets
   ```

2. Add this marketplace and install the plugin in Claude Code:

   ```
   /plugin marketplace add phuchuynhStrong/mission_pipeline
   /plugin install pipeline@mission-pipeline
   ```

3. Type `/pipeline` with a ticket id, or hand over a feature or bug in words. Add
   `--plan-only` (or type `/pipeplan`) to stop after the plan: read > spec > plan, then
   `spec.md` + `plan.html` are committed to `docs/preparation/<id>-<slug>/` on the current
   branch. No worktree, no build, no ticket status change.

## Persistent coordinator

One long-lived coordinator session runs every mission on this Mac, in its own Orca terminal
and workspace, apart from your daily repo. Other tools and Claude sessions talk to it with
`orca orchestration send --to run:<shared> --type question`. `<root>` below is the installed
plugin folder; `<shared>` comes from `python3 -I <root>/scripts/state.py run`.

1. Create the workspace folder (default `~/orca/pipeline-coordinator`). Make it a git repo,
   so `orca repo add` accepts it:

   ```
   mkdir -p ~/orca/pipeline-coordinator
   git -C ~/orca/pipeline-coordinator init
   orca repo add --path ~/orca/pipeline-coordinator
   ```

2. Write its settings (accept-edits mode, the narrow allowlist, the `/compact` notes hook):

   ```
   mkdir -p ~/orca/pipeline-coordinator/.claude
   python3 -I <root>/scripts/coordinator_setup.py settings --plugin-root <root> > ~/orca/pipeline-coordinator/.claude/settings.json
   ```

3. Cutover rule: start the dedicated coordinator only when no open mission has a live
   worker. First launch by hand, and answer the one-time folder trust dialog:

   ```
   orca agent launch --agent claude --surface terminal --worktree path:$HOME/orca/pipeline-coordinator --prompt "/pipeline" --json
   ```

   Its first Binding takes over the shared Run, seeds the inbox scan, and re-arms the PR
   watchers. Then close the old coordinator session in your daily repo.

4. Install the watchdog. It runs every minute and at login, starts a new coordinator when
   the saved terminal is gone, and never types into any terminal:

   ```
   python3 -I <root>/scripts/watchdog.py plist --workspace ~/orca/pipeline-coordinator > ~/Library/LaunchAgents/com.mission-pipeline.coordinator-watchdog.plist
   launchctl load ~/Library/LaunchAgents/com.mission-pipeline.coordinator-watchdog.plist
   ```

5. When the coordinator is live but not waiting (fenced, a permission prompt, Binding
   failed), the watchdog writes a notice to the board and does not launch. A new watchdog
   notice replaces the older open ones, and the next ok check clears them. After two failed
   launches in a row it pauses. Fix the cause, then:

   ```
   python3 -I <root>/scripts/watchdog.py resume
   ```

6. After every plugin update, run step 2 (settings) and step 4 (plist, then `launchctl
   unload` and `load` it again) once more: both files hold `<root>`, and `<root>` holds the
   plugin version, so the old paths point at a folder that is gone.

## For tool authors

A tool (or another Claude session) asks the coordinator through Orca, never by typing into
its terminal:

1. Find the Run: `python3 -I <root>/scripts/state.py run` → `<shared>`.
2. Send: `orca orchestration send --to run:<shared> --type question --subject '<title>'
   --body '<text>' --json`. Keep the `messageId` from the receipt.
3. Wait in your own terminal: `orca orchestration check --wait --full --json` (add
   `--timeout-ms <n>`). The answer is a `status` message whose `thread_id` is your
   `messageId`; one batch can hold several replies, keep the ones you did not match.
4. On a timeout, wait again. Never send the question again: the coordinator would act twice.
5. Lost the `check` result (crash, context loss)? Find the reply with `orca orchestration
   inbox --terminal <own handle> --full --json`, matched by `thread_id`.
6. Stay in a live Orca terminal until you have read the answer.
7. A worker of another Run cannot send to the shared Run (`dispatch_run_mismatch`); only
   plain terminals can.

## Layout

```
.claude-plugin/plugin.json     plugin manifest (userConfig.root = state folder)
.claude-plugin/marketplace.json
skills/pipeline/SKILL.md       the coordinator skill
skills/pipeline/references/    Orca command list, worker role specs
commands/pipeplan.md           /pipeplan: the pipeline in plan mode
hooks/                         /pboard pane (register.tsx, hooks.json, test)
scripts/state.py               mission state: new / set / done / abort / show / list
types/index.d.ts               Mission state types shared by the hook and the test
```

Mission state lives outside git in `~/.claude/pipeline/<repo-basename>/<id>.json`.
Change the folder with the plugin's `root` user config.

## Known gap

The board pane is a plugin hook module (`hooks/register.tsx`). It was developed with the
skill installed under `~/.claude/skills/pipeline`. Loading it from a marketplace install has
not been verified yet. If `/pboard` does not open, report it in an issue.
