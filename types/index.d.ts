export type StageStatus = 'pending' | 'active' | 'waiting_user' | 'done' | 'failed'

/** `pr` = PR open, Greptile check running or waiting on the user. `ready` = Greptile done, PR not yet merged. `aborted` and `done` are terminal: the board hides them and never auto-opens for them. */
export type MissionStageName = 'read' | 'spec' | 'plan' | 'worktree' | 'build' | 'review' | 'pr' | 'ready' | 'done' | 'aborted'

export type MissionStage = { status: StageStatus }

/** Set by the coordinator while a mission waits on the user; the board draws a `switch` button for it. */
export type MissionAttention = { terminal: string; reason: string }

export type Mission = {
  id: string
  ticket: string
  title: string
  repo_slug: string
  stage: MissionStageName | string
  note: string
  updated: string
  stages: Record<string, MissionStage>
  attention?: MissionAttention | null
}
