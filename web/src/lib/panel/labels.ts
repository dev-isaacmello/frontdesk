/**
 * The words the owner reads in place of the names the API uses. A name this file does not
 * know gets a neutral sentence, never the raw identifier.
 */

import { formatDayAndTime, formatListTime } from "./format";
import type { Approval, Author, ConversationRow, ConversationSummary, Step } from "./types";

export const AGENT_NAME = "Atendente automático";
export const UNNAMED_CUSTOMER = "Cliente sem nome";
const PREVIEW_LIMIT = 90;

export function customerName(name: string | null): string {
  return name?.trim() || UNNAMED_CUSTOMER;
}

export function authorLabel(author: Author): string {
  if (author === "agent") {
    return AGENT_NAME;
  }
  return author === "owner" ? "Você" : "Cliente";
}

/** Joins "a", "b" and "c" as a sentence does: "a, b e c". */
function sentenceList(items: readonly string[]): string {
  if (items.length <= 1) {
    return items.join("");
  }
  return `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}`;
}

function capitalized(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function conversationRow(conversation: ConversationSummary, now: Date): ConversationRow {
  const prefix =
    conversation.last_author === "agent"
      ? "Atendente: "
      : conversation.last_author === "owner"
        ? "Você: "
        : "";
  const text = conversation.last_message_preview.replace(/\s+/g, " ").trim();
  // The API cuts the preview without saying so. A preview of the full length was cut.
  const cut = conversation.last_message_preview.length >= PREVIEW_LIMIT;
  return {
    id: conversation.id,
    name: customerName(conversation.customer_name),
    named: Boolean(conversation.customer_name?.trim()),
    preview: `${prefix}${text}${cut ? "…" : ""}`,
    when: formatListTime(conversation.last_message_at, now),
    handoff: conversation.mode === "handoff",
    pendingApproval: conversation.pending_approval,
  };
}

const OUTCOMES: Record<string, string> = {
  replied: "Respondeu ao cliente",
  refused: "Recusou o pedido",
  handoff: "Passou a conversa para a equipe",
  awaiting_approval: "Parou para esperar a sua aprovação",
  silent: "Não respondeu porque a conversa está com a equipe",
  failed: "Não conseguiu responder",
};

/** What came out of one turn of the agent. */
export function outcomeLabel(outcome: string | null): string {
  return (outcome && OUTCOMES[outcome]) || "Ainda em andamento";
}

const HANDOFF_REASONS: Record<string, string> = {
  customer_asked: "O cliente pediu para falar com uma pessoa",
  agent_failed: "O atendente automático não conseguiu responder",
  guardrail_blocked: "A resposta foi barrada na revisão mais de uma vez",
  turn_limit: "O pedido precisou de passos demais",
  budget_exhausted: "O limite de gasto do atendimento foi atingido",
};

export function handoffReasonLabel(reason: unknown): string | undefined {
  return typeof reason === "string" ? HANDOFF_REASONS[reason] : undefined;
}

const TOOL_PLANS: Record<string, string> = {
  list_services: "ver os serviços e preços",
  quote: "calcular o valor",
  check_availability: "ver os horários livres",
  create_booking: "marcar o horário",
  list_customer_bookings: "ver os horários do cliente",
  cancel_booking: "cancelar o horário",
  reschedule_booking: "remarcar o horário",
};

const EFFECTS: Record<string, string> = {
  booked: "marcou o horário",
  cancelled: "cancelou o horário",
  rescheduled: "remarcou o horário",
  listed: "encontrou os horários do cliente",
};

function known(values: unknown, names: Record<string, string>, fallback: string): string[] {
  const list = Array.isArray(values) ? values : [];
  const phrases = list.map((value) => (typeof value === "string" && names[value]) || fallback);
  return [...new Set(phrases)];
}

/** `attention` marks a step that stopped or changed the usual course of a reply. */
export type StepLabel = { title: string; note?: string; attention?: boolean };

/** One step of a turn, in the words of someone who watched it happen. */
export function stepLabel(step: Pick<Step, "node" | "detail">): StepLabel {
  const detail = step.detail ?? {};
  switch (step.node) {
    case "load_context":
      return { title: "Leu a conversa e os dados do negócio" };
    case "classify":
      if (detail.wants_human === true) {
        return {
          title: "Entendeu o pedido",
          note: "O cliente quer falar com uma pessoa",
          attention: true,
        };
      }
      if (detail.in_scope === false) {
        return { title: "Entendeu o pedido", note: "Não é assunto do negócio", attention: true };
      }
      return { title: "Entendeu o pedido", note: "É assunto do negócio" };
    case "plan": {
      const plans = known(detail.tools, TOOL_PLANS, "consultar o sistema");
      if (plans.length > 0) {
        return { title: `Decidiu ${sentenceList(plans)}` };
      }
      return detail.wrote_reply === true
        ? { title: "Escreveu a resposta" }
        : { title: "Pensou no próximo passo", note: "Ainda sem resposta para enviar" };
    }
    case "gate":
      if (detail.decision === "wait") {
        return {
          title: "Conferiu se podia seguir",
          note: "Precisa da sua aprovação",
          attention: true,
        };
      }
      if (detail.decision === "deny") {
        return { title: "Conferiu se podia seguir", note: "Não liberado", attention: true };
      }
      return { title: "Conferiu se podia seguir", note: "Liberado" };
    case "await_approval":
      if (detail.decision === "allow") {
        return { title: "Esperou a sua decisão", note: "Você aprovou" };
      }
      if (detail.decision === "deny") {
        return { title: "Esperou a sua decisão", note: "Você recusou", attention: true };
      }
      return { title: "Esperou a sua decisão" };
    case "execute": {
      const effects = known(detail.effects, EFFECTS, "alterou a agenda");
      return effects.length > 0
        ? { title: capitalized(sentenceList(effects)) }
        : { title: "Consultou o sistema", note: "Nada foi alterado na agenda" };
    }
    case "validate":
      return detail.passed === false
        ? { title: "Revisou a resposta antes de enviar", note: "Barrada na revisão", attention: true }
        : { title: "Revisou a resposta antes de enviar", note: "Aprovada" };
    case "handoff":
      return {
        title: "Passou a conversa para a equipe",
        note: handoffReasonLabel(detail.reason),
        attention: true,
      };
    case "refuse":
      return { title: "Recusou o pedido", note: "Não é assunto do negócio", attention: true };
    default:
      return { title: "Etapa interna do atendimento" };
  }
}

const CLAUSES: Record<string, string> = {
  discount:
    "O atendente automático nunca dá desconto, promoção, brinde ou gratuidade, mesmo que a regra peça.",
  price_outside_catalog:
    "Preço só vem do cadastro de serviços. Uma regra não cria, muda nem combina preços.",
  action_without_tool:
    "Marcar, remarcar e cancelar só acontecem pelo sistema. O atendente automático não promete nem confirma nada fora dele.",
  outside_business:
    "O atendente automático só trata de assuntos do seu negócio: serviços, preços, horários e agendamentos.",
};

/** Why an excerpt of the house rules will have no effect. */
export function clauseExplanation(clause: string): string {
  return CLAUSES[clause] ?? "Esse trecho vai contra uma proteção fixa do atendimento.";
}

const APPROVAL_VERBS: Record<string, string> = {
  cancel_booking: "Cancelar",
  reschedule_booking: "Remarcar",
};

/** What the customer asked for, in one line: "Cancelar Corte com Renan, quinta 19/11 às 14:00". */
export function approvalSummary(
  approval: Pick<Approval, "tool" | "service_name" | "resource_name" | "starts_at">,
): string {
  const verb = APPROVAL_VERBS[approval.tool];
  if (!verb) {
    return "Um pedido que precisa da sua decisão";
  }
  const service = approval.service_name?.trim();
  const resource = approval.resource_name?.trim();
  const when = approval.starts_at ? formatDayAndTime(approval.starts_at) : "";
  if (!service && !resource && !when) {
    return `${verb} um horário que não está mais na agenda`;
  }
  const what = [service || "um horário", resource ? `com ${resource}` : ""].filter(Boolean);
  if (!when) {
    return `${verb} ${what.join(" ")}`;
  }
  // The API tells when the booking is today, not the time the customer wants instead.
  return approval.tool === "reschedule_booking"
    ? `${verb} ${what.join(" ")}, de ${when} para outro horário`
    : `${verb} ${what.join(" ")}, ${when}`;
}

/** Why the request stopped to wait for the owner. */
export function approvalReason(rule: string): string {
  return rule === "late_change"
    ? "O pedido chegou em cima da hora, por isso depende de você."
    : "Esse tipo de pedido depende de você.";
}
