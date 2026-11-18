import { redirect } from "next/navigation";

import { sessionIsKnown, SIGN_IN_PATH } from "@/server/owner-api";
import { closeOwnerSession, ownerToken } from "@/server/owner-session";

/**
 * Where the panel sends an owner whose session the API refused. A page cannot change a
 * cookie while it renders, so this handler does it. It asks the API again first: a link
 * to this address planted on another site must not sign anyone out.
 */
export async function GET() {
  const token = await ownerToken();
  if (!token) {
    redirect(SIGN_IN_PATH);
  }
  const known = await sessionIsKnown(token);
  if (known === true) {
    redirect("/painel");
  }
  if (known === false) {
    await closeOwnerSession();
    redirect(`${SIGN_IN_PATH}?motivo=sessao`);
  }
  redirect(`${SIGN_IN_PATH}?motivo=indisponivel`);
}
