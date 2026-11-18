import { formatCost, formatDuration } from "./format";

export type ComparisonEntry = {
  model: string;
  prompt_version: string;
  runs: number;
  last_run_at: string;
  cases: number;
  passed_per_run: number[];
  passed_mean: number;
  cost_per_conversation_microusd: number;
  model_ms_per_turn_p50: number;
  blocked_drafts_mean: number;
  by_category: Record<string, { cases: number; passed_mean: number }>;
  always_failing: string[];
  unstable: string[];
};

export type Comparison = {
  golden_version: string;
  entries: ComparisonEntry[];
  excluded: { model: string; reason: string; reason_pt?: string }[];
};

const CATEGORIES: Record<string, string> = {
  tools: "Consultar o sistema antes de responder",
  arguments: "Agendar, mudar e cancelar",
  numbers: "Preços e horários certos",
  policy: "Descontos e regras da casa",
  refusal: "Assuntos fora do negócio",
  injection: "Tentativas de enganar o atendente",
  approval: "Pedidos que dependem de você",
  handoff: "Passar para uma pessoa",
};

export function categoryLabel(category: string): string {
  return CATEGORIES[category] ?? "Outros testes";
}

/** The entries with the newest instructions of each model, the best first. */
export function latestPerModel(comparison: Comparison): ComparisonEntry[] {
  const newest = new Map<string, ComparisonEntry>();
  for (const entry of comparison.entries) {
    const known = newest.get(entry.model);
    if (!known || entry.last_run_at > known.last_run_at) {
      newest.set(entry.model, entry);
    }
  }
  return [...newest.values()].sort(
    (a, b) =>
      b.passed_mean - a.passed_mean ||
      a.cost_per_conversation_microusd - b.cost_per_conversation_microusd,
  );
}

/** The same model before and after a change of instructions, when both were measured. */
export function beforeAndAfter(
  comparison: Comparison,
  model: string,
): { before: ComparisonEntry; after: ComparisonEntry } | undefined {
  const versions = comparison.entries
    .filter((entry) => entry.model === model)
    .sort((a, b) => a.last_run_at.localeCompare(b.last_run_at));
  const after = versions.at(-1);
  // Runs of the earlier instructions with the same number of rounds make the fairest pair.
  const before = versions.slice(0, -1).findLast((entry) => entry.runs === after?.runs);
  return before && after ? { before, after } : undefined;
}

/** "31, 31 e 31 de 32" */
export function passedPerRun(entry: ComparisonEntry): string {
  const rounds = entry.passed_per_run.map(String);
  const listed =
    rounds.length > 1 ? `${rounds.slice(0, -1).join(", ")} e ${rounds.at(-1)}` : rounds[0];
  return `${listed} de ${entry.cases}`;
}

/** "31,0" */
export function meanPassed(entry: ComparisonEntry): string {
  return entry.passed_mean.toFixed(1).replace(".", ",");
}

export function costPerConversation(entry: ComparisonEntry): string {
  return formatCost(entry.cost_per_conversation_microusd);
}

export function timePerReply(entry: ComparisonEntry): string {
  return formatDuration(entry.model_ms_per_turn_p50);
}

/** How many times cheaper or dearer, and faster or slower, one model is than another. */
export function ratio(value: number, reference: number): string {
  if (reference <= 0 || value <= 0) {
    return "";
  }
  const times = reference / value;
  const shown = (times >= 1 ? times : 1 / times).toFixed(1).replace(".", ",");
  return times >= 1 ? `${shown} vezes menos` : `${shown} vezes mais`;
}
