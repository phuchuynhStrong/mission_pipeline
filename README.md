# mission_pipeline

A Claude Code plugin. It ships the `pipeline` skill, the `/pipeline-board` pane, and the
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

3. Type `/pipeline` with a ticket id, or hand over a feature or bug in words.

## Layout

```
.claude-plugin/plugin.json     plugin manifest (userConfig.root = state folder)
.claude-plugin/marketplace.json
skills/pipeline/SKILL.md       the coordinator skill
skills/pipeline/references/    Orca command list, worker role specs
hooks/                         /pipeline-board pane (register.tsx, hooks.json, test)
scripts/state.py               mission state: new / set / done / abort / show / list
types/index.d.ts               Mission state types shared by the hook and the test
```

Mission state lives outside git in `~/.claude/pipeline/<repo-basename>/<id>.json`.
Change the folder with the plugin's `root` user config.

## Known gap

The board pane is a plugin hook module (`hooks/register.tsx`). It was developed with the
skill installed under `~/.claude/skills/pipeline`. Loading it from a marketplace install has
not been verified yet. If `/pipeline-board` does not open, report it in an issue.
