import { formatCost, formatDuration } from "@/lib/panel/format";
import { outcomeLabel, stepLabel } from "@/lib/panel/labels";
import { turnDurationMs } from "@/lib/panel/thread";
import type { Turn } from "@/lib/panel/types";

import { Chevron } from "./icons";

/** How one reply was made: closed it is a line, open it lists every step of the turn. */
export function TurnTimeline({ turn }: { turn: Turn }) {
  const duration = formatDuration(turnDurationMs(turn));
  const cost = formatCost(turn.cost_microusd);
  const steps = [...turn.steps].sort((one, other) => one.seq - other.seq);

  return (
    <details className="group/turn w-full max-w-md">
      <summary className="flex cursor-pointer list-none items-center justify-end gap-1 py-1 text-sm text-ink-soft hover:text-ink [&::-webkit-details-marker]:hidden">
        <span>
          Como foi feita: {duration}, {cost}
        </span>
        <Chevron direction="down" className="size-4 transition-transform group-open/turn:rotate-180" />
      </summary>

      <div className="mt-1 mb-3 rounded-2xl border border-line px-4 py-4 text-left text-[15px]">
        <p className="font-medium">{outcomeLabel(turn.outcome)}</p>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
          <Fact term="Tempo" value={duration} />
          <Fact term="Custo" value={cost} />
          <Fact term="Chamadas à IA" value={String(turn.model_calls)} />
          <Fact
            term="Rascunhos barrados"
            value={turn.blocked_drafts > 0 ? String(turn.blocked_drafts) : "Nenhum"}
          />
        </dl>

        {steps.length === 0 ? (
          <p className="mt-4 border-t border-line pt-3 text-ink-soft">
            Os passos desta resposta não foram registrados.
          </p>
        ) : (
          <ol className="mt-4 border-t border-line pt-4">
            {steps.map((step, index) => {
              const label = stepLabel(step);
              return (
                <li key={step.seq} className="relative flex gap-3 pb-3 last:pb-0">
                  {index < steps.length - 1 ? (
                    <span aria-hidden="true" className="absolute top-3 bottom-0 left-[3px] w-px bg-line" />
                  ) : null}
                  <span
                    aria-hidden="true"
                    className={`relative mt-[7px] size-[7px] shrink-0 rounded-full ${
                      label.attention ? "bg-attention" : "bg-ink-soft"
                    }`}
                  />
                  <span className="min-w-0 flex-1 leading-snug">
                    {label.title}
                    {label.note ? (
                      <span className={label.attention ? "text-attention" : "text-ink-soft"}>
                        {`: ${label.note.charAt(0).toLowerCase()}${label.note.slice(1)}`}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 text-sm leading-snug text-ink-soft tabular-nums">
                    {formatDuration(step.duration_ms)}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </details>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-ink-soft">{term}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
