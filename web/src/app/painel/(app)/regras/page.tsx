import { Suspense } from "react";

import { formatMoment } from "@/lib/panel/format";
import { getRules } from "@/server/owner-api";

import { PageHeader } from "../../_components/page-header";
import { RulesEditor } from "../../_components/rules-editor";
import { Bar, Loading, LoadFailed } from "../../_components/states";

export default function RulesPage() {
  return (
    <div className="pb-24 lg:h-full lg:overflow-y-auto lg:pb-10">
      <div className="max-w-6xl">
        <PageHeader
          title="Regras da casa"
          lead="Escreva do seu jeito o que o atendente automático deve saber e seguir. As regras salvas valem a partir da próxima mensagem de cada cliente."
        />
        <Suspense fallback={<RulesLoading />}>
          <Rules />
        </Suspense>
      </div>
    </div>
  );
}

async function Rules() {
  const result = await getRules();
  if (!result.ok) {
    return <LoadFailed what="as regras" />;
  }
  const rules = result.value;
  return (
    <RulesEditor
      initial={rules}
      initialSavedAt={rules.saved_at ? formatMoment(rules.saved_at, new Date()) : ""}
    />
  );
}

function RulesLoading() {
  return (
    <Loading label="Carregando as regras">
      <div className="px-4 pt-2 lg:px-8">
        <Bar className="h-64 w-full rounded-2xl lg:w-3/5" />
        <Bar className="mt-4 h-12 w-40 rounded-full" />
      </div>
    </Loading>
  );
}
