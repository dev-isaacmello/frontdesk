/** The owner's side of the API, as the panel reads it. */

export type Author = "customer" | "agent" | "owner";
export type Mode = "agent" | "handoff";

export type ConversationSummary = {
  id: string;
  customer_name: string | null;
  mode: Mode;
  last_message_at: string;
  last_message_preview: string;
  last_author: Author;
  pending_approval: boolean;
};

export type ConversationList = {
  tenant: { slug: string; name: string };
  conversations: ConversationSummary[];
};

export type Message = { id: string; author: Author; text: string; at: string };

export type Step = {
  seq: number;
  node: string;
  duration_ms: number;
  detail: Record<string, unknown>;
};

export type Turn = {
  id: string;
  status: string;
  outcome: string | null;
  started_at: string;
  finished_at: string | null;
  blocked_drafts: number;
  model_calls: number;
  cost_microusd: number;
  steps: Step[];
};

export type ConversationDetail = {
  id: string;
  customer_name: string | null;
  mode: Mode;
  messages: Message[];
  turns: Turn[];
};

export type Approval = {
  id: string;
  conversation_id: string;
  customer_name: string | null;
  rule: string;
  tool: string;
  requested_at: string;
  service_name: string | null;
  resource_name: string | null;
  starts_at: string | null;
};

export type Finding = { clause: string; excerpt: string; source: "code" | "model" };

export type Rules = {
  version: number;
  body: string;
  saved_at: string | null;
  findings: Finding[];
  /** Null when the rules were only read. False when the automatic review did not finish. */
  checked_by_model: boolean | null;
};

/** A row of the conversation list, already worded for the screen. */
export type ConversationRow = {
  id: string;
  name: string;
  named: boolean;
  preview: string;
  when: string;
  handoff: boolean;
  pendingApproval: boolean;
};
