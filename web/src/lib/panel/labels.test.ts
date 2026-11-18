import { describe, expect, it } from "vitest";

import {
  approvalReason,
  approvalSummary,
  authorLabel,
  clauseExplanation,
  conversationRow,
  handoffReasonLabel,
  outcomeLabel,
  stepLabel,
} from "./labels";

const IDENTIFIER = /[a-z]+_[a-z]+/;

describe("stepLabel", () => {
  it("says what the agent decided to look up or do", () => {
    expect(stepLabel({ node: "plan", detail: { tools: ["quote"] } }).title).toBe(
      "Decidiu calcular o valor",
    );
    expect(
      stepLabel({ node: "plan", detail: { tools: ["list_services", "list_customer_bookings"] } })
        .title,
    ).toBe("Decidiu ver os serviços e preços e ver os horários do cliente");
    expect(stepLabel({ node: "plan", detail: { wrote_reply: true } }).title).toBe(
      "Escreveu a resposta",
    );
  });

  it("says what the check before acting decided", () => {
    expect(stepLabel({ node: "gate", detail: { decision: "allow" } })).toEqual({
      title: "Conferiu se podia seguir",
      note: "Liberado",
    });
    expect(stepLabel({ node: "gate", detail: { decision: "wait" } }).note).toBe(
      "Precisa da sua aprovação",
    );
    expect(stepLabel({ node: "gate", detail: { decision: "deny" } }).note).toBe("Não liberado");
    expect(stepLabel({ node: "await_approval", detail: { decision: "deny" } }).note).toBe(
      "Você recusou",
    );
  });

  it("tells a lookup from a change to the schedule", () => {
    expect(stepLabel({ node: "execute", detail: { effects: [], results: 1 } })).toEqual({
      title: "Consultou o sistema",
      note: "Nada foi alterado na agenda",
    });
    expect(stepLabel({ node: "execute", detail: { effects: ["booked"], results: 1 } }).title).toBe(
      "Marcou o horário",
    );
    expect(
      stepLabel({ node: "execute", detail: { effects: ["listed", "cancelled"], results: 2 } }).title,
    ).toBe("Encontrou os horários do cliente e cancelou o horário");
  });

  it("says why a conversation went to the team", () => {
    expect(stepLabel({ node: "handoff", detail: { reason: "customer_asked" } })).toEqual({
      title: "Passou a conversa para a equipe",
      note: "O cliente pediu para falar com uma pessoa",
      attention: true,
    });
    expect(handoffReasonLabel("something_new")).toBeUndefined();
  });

  it("reports a reply that the review held back", () => {
    expect(stepLabel({ node: "validate", detail: { passed: false } }).note).toBe(
      "Barrada na revisão",
    );
    expect(stepLabel({ node: "validate", detail: { passed: true } }).note).toBe("Aprovada");
  });

  it("never shows the name of a step, a tool or an effect", () => {
    const steps = [
      { node: "load_context", detail: {} },
      { node: "classify", detail: { in_scope: false, wants_human: false } },
      { node: "classify", detail: { in_scope: true, wants_human: true } },
      { node: "plan", detail: { tools: ["a_tool_from_the_future"] } },
      { node: "plan", detail: {} },
      { node: "gate", detail: { decision: "something_else" } },
      { node: "await_approval", detail: {} },
      { node: "execute", detail: { effects: ["an_effect_from_the_future"] } },
      { node: "validate", detail: {} },
      { node: "handoff", detail: { reason: "a_new_reason" } },
      { node: "refuse", detail: {} },
      { node: "a_node_from_the_future", detail: {} },
    ];
    for (const step of steps) {
      const label = stepLabel(step);
      expect(label.title).not.toMatch(IDENTIFIER);
      expect(label.note ?? "").not.toMatch(IDENTIFIER);
      expect(label.title.length).toBeGreaterThan(0);
    }
  });
});

describe("outcomeLabel", () => {
  it("puts every outcome in plain words", () => {
    expect(outcomeLabel("replied")).toBe("Respondeu ao cliente");
    expect(outcomeLabel("awaiting_approval")).toBe("Parou para esperar a sua aprovação");
    expect(outcomeLabel("failed")).toBe("Não conseguiu responder");
    for (const outcome of ["refused", "handoff", "silent", "an_outcome_from_the_future", null]) {
      expect(outcomeLabel(outcome)).not.toMatch(IDENTIFIER);
    }
  });
});

describe("clauseExplanation", () => {
  it("explains every clause and never shows its name", () => {
    const clauses = ["discount", "price_outside_catalog", "action_without_tool", "outside_business"];
    const texts = clauses.map(clauseExplanation);
    expect(new Set(texts).size).toBe(clauses.length);
    for (const text of [...texts, clauseExplanation("a_new_clause")]) {
      expect(text).not.toMatch(IDENTIFIER);
    }
  });
});

describe("approvalSummary", () => {
  const booking = {
    service_name: "Corte",
    resource_name: "Renan",
    starts_at: "2026-11-19T17:00:00Z",
  };

  it("says what the customer asked for in one line", () => {
    expect(approvalSummary({ tool: "cancel_booking", ...booking })).toBe(
      "Cancelar Corte com Renan, quinta 19/11 às 14:00",
    );
  });

  it("does not present the current time of a booking as the new one", () => {
    expect(approvalSummary({ tool: "reschedule_booking", ...booking })).toBe(
      "Remarcar Corte com Renan, de quinta 19/11 às 14:00 para outro horário",
    );
  });

  it("still reads well when the booking is gone or the request is of a new kind", () => {
    const gone = { service_name: null, resource_name: null, starts_at: null };
    expect(approvalSummary({ tool: "cancel_booking", ...gone })).toBe(
      "Cancelar um horário que não está mais na agenda",
    );
    expect(approvalSummary({ tool: "cancel_booking", ...booking, resource_name: null })).toBe(
      "Cancelar Corte, quinta 19/11 às 14:00",
    );
    expect(approvalSummary({ tool: "refund_payment", ...booking })).toBe(
      "Um pedido que precisa da sua decisão",
    );
  });

  it("explains the rule without naming it", () => {
    expect(approvalReason("late_change")).toContain("em cima da hora");
    expect(approvalReason("a_new_rule")).not.toMatch(IDENTIFIER);
  });
});

describe("conversationRow", () => {
  const now = new Date("2026-11-18T01:30:00Z");
  const summary = {
    id: "c1",
    customer_name: null,
    mode: "handoff" as const,
    last_message_at: "2026-11-18T01:09:14Z",
    last_message_preview: "Vou chamar uma pessoa\nda equipe",
    last_author: "agent" as const,
    pending_approval: false,
  };

  it("words a row for a customer the business does not know by name", () => {
    expect(conversationRow(summary, now)).toEqual({
      id: "c1",
      name: "Cliente sem nome",
      named: false,
      preview: "Atendente: Vou chamar uma pessoa da equipe",
      when: "22:09",
      handoff: true,
      pendingApproval: false,
    });
  });

  it("marks a preview the API cut short", () => {
    const row = conversationRow({ ...summary, last_message_preview: "a".repeat(90) }, now);
    expect(row.preview.endsWith("…")).toBe(true);
  });

  it("says who wrote the last message", () => {
    const row = conversationRow(
      { ...summary, customer_name: " Marina ", last_author: "owner", last_message_preview: "Oi" },
      now,
    );
    expect(row.name).toBe("Marina");
    expect(row.preview).toBe("Você: Oi");
    expect(authorLabel("customer")).toBe("Cliente");
  });
});
