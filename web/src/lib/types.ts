export interface Template {
  id: string;
  name: string;
  description: string;
  tools: string[];
  model: string;
}

export interface TemplateDetail extends Template {
  max_tokens: number;
  system_prompt: string;
  resources: Record<string, number>;
}

export interface TriggerDefinition {
  type: "cron" | "agent_output";
  expression?: string;
  timezone?: string;
  source_agent?: string;
  output_name?: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  owner: string;
  template: string;
  triggers: TriggerDefinition[];
  enabled: boolean;
  last_run_status: string | null;
  last_run_at: string | null;
  outputs_count: number;
  runs_today: number;
  max_runs_per_day: number;
}

export interface OutputDefinition {
  name: string;
  description: string;
  trigger: string;
  type: string;
  destination: string;
  format: string;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  id: string;
}

export interface ConversationTurn {
  step: number;
  timestamp: string;
  role: string;
  text: string | null;
  tool_calls: ToolCall[] | null;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_error: boolean;
}

export interface AgentRun {
  run_id: string;
  agent_id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  trigger: string;
  error: string | null;
  outputs_produced: string[];
  tool_call_counts: Record<string, number>;
}

export interface RunDetail extends AgentRun {
  turns: ConversationTurn[];
}

export interface AgentDetail extends AgentSummary {
  mission_md: string;
  outputs: OutputDefinition[];
  resources: string[];
  tools: string[];
  model: string;
  last_run: AgentRun | null;
}
