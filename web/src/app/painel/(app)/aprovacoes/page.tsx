import { Suspense } from "react";

import { formatMoment } from "@/lib/panel/format";
import { approvalReason, approvalSummary, customerName } from "@/lib/panel/labels";
import { listApprovals } from "@/server/owner-api";

import { ApprovalQueue } from "../../_components/approval-queue";
import { PageHeader } from "../../_components/page-header";
import { Bar, Loading, LoadFailed } from "../../_components/states";

export default function ApprovalsPage() {
  return (
    <div className="pb-24 lg:h-full lg:overflow-y-auto lg:pb-10">
      <div className="max-w-4xl">
        <PageHeader
          title="Aprovações"
          lead="Pedidos que o atendente automático não decide sozinho. O cliente fica esperando a sua resposta."
        />
        <Suspense fallback={<ApprovalsLoading />}>
          <Approvals />
        </Suspense>
      </div>
    </div>
  );
}

async function Approvals() {
  const result = await listApprovals();
  if (!result.ok) {
    return <LoadFailed what="os pedidos" />;
  }
  const now = new Date();
  return (
    <ApprovalQueue
      requests={result.value.map((approval) => ({
        id: approval.id,
        conversationId: approval.conversation_id,
        summary: approvalSummary(approval),
        detail: `${customerName(approval.customer_name)} pediu ${formatMoment(approval.requested_at, now)}. ${approvalReason(approval.rule)}`,
      }))}
    />
  );
}

function ApprovalsLoading() {
  return (
    <Loading label="Carregando os pedidos">
      <div className="mt-2 border-y border-line px-4 py-6 lg:px-8">
        <Bar className="h-6 w-4/5 lg:w-1/2" />
        <Bar className="mt-3 h-4 w-11/12 lg:w-2/3" />
        <Bar className="mt-6 h-12 w-full rounded-full lg:w-64" />
      </div>
    </Loading>
  );
}
