import comparisonData from "@/data/model-comparison.json";
import {
  beforeAndAfter,
  categoryLabel,
  costPerConversation,
  latestPerModel,
  meanPassed,
  passedPerRun,
  ratio,
  timePerReply,
  type Comparison,
  type ComparisonEntry,
} from "@/lib/panel/models";

import { PageHeader } from "../../_components/page-header";

const comparison = comparisonData as Comparison;

// The model the first measurements were made with, kept as the yardstick for the others.
const REFERENCE = "gpt-5-mini";

export default function ModelsPage() {
  const models = latestPerModel(comparison);
  const best = models[0];
  const reference = models.find((each) => each.model === REFERENCE);
  const change = beforeAndAfter(comparison, REFERENCE);
  return (
    <div className="pb-24 lg:h-full lg:overflow-y-auto lg:pb-10">
      <div className="max-w-5xl">
        <PageHeader
          title="Modelos de IA"
          lead={`As mesmas ${best?.cases ?? 0} conversas de teste foram feitas com cada modelo que esta conta pode usar. Um modelo não responde igual duas vezes, então cada um passou pelo teste mais de uma vez.`}
        />
        {models.length === 0 ? (
          <p className="px-4 py-10 text-ink-soft lg:px-8">Nenhum modelo foi medido ainda.</p>
        ) : (
          <>
            <Phone models={models} best={best} reference={reference} />
            <Desktop models={models} best={best} reference={reference} />
          </>
        )}
        {change ? <Change before={change.before} after={change.after} /> : null}
        <LeftOut />
        <p className="px-4 pt-8 text-sm text-ink-soft lg:px-8">
          O teste confere se o atendente consultou o sistema, o que a resposta afirma e o que ficou
          na agenda. São poucas conversas e poucas rodadas: serve para comparar, não para
          garantir.
        </p>
      </div>
    </div>
  );
}

type Shown = { models: ComparisonEntry[]; best?: ComparisonEntry; reference?: ComparisonEntry };

function against(entry: ComparisonEntry, reference: ComparisonEntry | undefined) {
  if (!reference || reference.model === entry.model) {
    return { cost: "", time: "" };
  }
  const than = (times: string) => (times ? `${times} que o ${reference.model}` : "");
  return {
    cost: than(
      ratio(entry.cost_per_conversation_microusd, reference.cost_per_conversation_microusd),
    ),
    time: than(ratio(entry.model_ms_per_turn_p50, reference.model_ms_per_turn_p50)),
  };
}

function Recommended() {
  return (
    <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs font-semibold text-accent-ink">
      Melhor resultado
    </span>
  );
}

/** One card per model, to be read from top to bottom with a thumb. */
function Phone({ models, best, reference }: Shown) {
  return (
    <ul className="mt-2 divide-y divide-line border-y border-line lg:hidden">
      {models.map((entry) => {
        const compared = against(entry, reference);
        return (
          <li key={entry.model} className="px-4 py-6">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 className="text-xl font-semibold">{entry.model}</h2>
              {entry === best ? <Recommended /> : null}
            </div>
            <p className="mt-3 text-4xl font-semibold tracking-tight">
              {meanPassed(entry)}
              <span className="text-lg font-normal text-ink-soft"> de {entry.cases} acertos</span>
            </p>
            <p className="mt-1 text-ink-soft">Por rodada: {passedPerRun(entry)}.</p>
            <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4">
              <div>
                <dt className="text-sm text-ink-soft">Custo por conversa</dt>
                <dd className="font-medium">{costPerConversation(entry)}</dd>
                {compared.cost ? <dd className="text-sm text-ink-soft">{compared.cost}</dd> : null}
              </div>
              <div>
                <dt className="text-sm text-ink-soft">Tempo de IA por resposta</dt>
                <dd className="font-medium">{timePerReply(entry)}</dd>
                {compared.time ? <dd className="text-sm text-ink-soft">{compared.time}</dd> : null}
              </div>
            </dl>
            <Unstable entry={entry} />
          </li>
        );
      })}
    </ul>
  );
}

/** The models side by side, one line per thing compared. */
function Desktop({ models, best, reference }: Shown) {
  const categories = Object.keys(models[0]?.by_category ?? {});
  return (
    <div className="mt-2 hidden px-8 lg:block">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line align-bottom">
            <th className="w-[30%] py-4 font-normal text-ink-soft">O que foi medido</th>
            {models.map((entry) => (
              <th key={entry.model} className="py-4 pl-6 font-semibold">
                <span className="block text-lg">{entry.model}</span>
                {entry === best ? (
                  <span className="mt-1 inline-block">
                    <Recommended />
                  </span>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <Row label="Acertos, em média">
            {models.map((entry) => (
              <td key={entry.model} className="py-4 pl-6 text-2xl font-semibold tracking-tight">
                {meanPassed(entry)}
                <span className="text-base font-normal text-ink-soft"> de {entry.cases}</span>
              </td>
            ))}
          </Row>
          <Row label="Acertos em cada rodada">
            {models.map((entry) => (
              <td key={entry.model} className="py-4 pl-6">
                {passedPerRun(entry)}
              </td>
            ))}
          </Row>
          <Row label="Custo por conversa">
            {models.map((entry) => (
              <Value key={entry.model} value={costPerConversation(entry)} note={against(entry, reference).cost} />
            ))}
          </Row>
          <Row label="Tempo de IA por resposta">
            {models.map((entry) => (
              <Value key={entry.model} value={timePerReply(entry)} note={against(entry, reference).time} />
            ))}
          </Row>
          {categories.map((category) => (
            <Row key={category} label={categoryLabel(category)} quiet>
              {models.map((entry) => {
                const tally = entry.by_category[category];
                return (
                  <td key={entry.model} className="py-3 pl-6 text-ink-soft">
                    {tally ? `${String(tally.passed_mean).replace(".", ",")} de ${tally.cases}` : ""}
                  </td>
                );
              })}
            </Row>
          ))}
          <Row label="Testes que ora passam, ora falham">
            {models.map((entry) => (
              <td key={entry.model} className="py-4 pl-6">
                {entry.unstable.length === 0 ? "Nenhum" : entry.unstable.length}
              </td>
            ))}
          </Row>
        </tbody>
      </table>
    </div>
  );
}

function Row({ label, quiet, children }: { label: string; quiet?: boolean; children: React.ReactNode }) {
  return (
    <tr className="border-b border-line align-top">
      <th scope="row" className={`font-normal ${quiet ? "py-3 text-ink-soft" : "py-4"}`}>
        {label}
      </th>
      {children}
    </tr>
  );
}

function Value({ value, note }: { value: string; note: string }) {
  return (
    <td className="py-4 pl-6">
      <span className="font-medium">{value}</span>
      {note ? <span className="block text-sm text-ink-soft">{note}</span> : null}
    </td>
  );
}

function Unstable({ entry }: { entry: ComparisonEntry }) {
  if (entry.unstable.length === 0) {
    return <p className="mt-4 text-sm text-ink-soft">Nenhum teste variou entre as rodadas.</p>;
  }
  const varied =
    entry.unstable.length === 1
      ? "1 teste passou em umas rodadas e falhou em outras."
      : `${entry.unstable.length} testes passaram em umas rodadas e falharam em outras.`;
  return <p className="mt-4 text-sm text-ink-soft">{varied}</p>;
}

function Change({ before, after }: { before: ComparisonEntry; after: ComparisonEntry }) {
  return (
    <section className="mt-10 px-4 lg:px-8">
      <h2 className="text-xl font-semibold">O efeito de mudar as instruções</h2>
      <p className="mt-2 max-w-2xl text-ink-soft">
        O {after.model} foi medido antes e depois de uma mudança no texto que orienta o atendente.
        Antes ele pedia dia e horário para só então dizer um preço.
      </p>
      <dl className="mt-5 grid max-w-2xl gap-5 sm:grid-cols-2">
        <div className="rounded-2xl border border-line p-5">
          <dt className="text-sm text-ink-soft">Antes</dt>
          <dd className="mt-1 text-2xl font-semibold tracking-tight">{meanPassed(before)}</dd>
          <dd className="text-sm text-ink-soft">Por rodada: {passedPerRun(before)}.</dd>
        </div>
        <div className="rounded-2xl border border-line p-5">
          <dt className="text-sm text-ink-soft">Depois</dt>
          <dd className="mt-1 text-2xl font-semibold tracking-tight">{meanPassed(after)}</dd>
          <dd className="text-sm text-ink-soft">Por rodada: {passedPerRun(after)}.</dd>
        </div>
      </dl>
    </section>
  );
}

function LeftOut() {
  if (comparison.excluded.length === 0) {
    return null;
  }
  return (
    <section className="mt-10 px-4 lg:px-8">
      <h2 className="text-xl font-semibold">Modelos que ficaram de fora</h2>
      <p className="mt-2 max-w-2xl text-ink-soft">
        A conta tem direito a usar estes modelos, mas eles não conseguem fazer o trabalho do
        atendente ou não puderam ser ligados.
      </p>
      <ul className="mt-4 max-w-3xl divide-y divide-line border-y border-line">
        {comparison.excluded.map((each) => (
          <li key={each.model} className="py-4">
            <p className="font-medium">{each.model}</p>
            <p className="mt-1 text-ink-soft">{each.reason_pt ?? each.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
