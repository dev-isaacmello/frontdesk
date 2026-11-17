import "server-only";

import { createHmac } from "node:crypto";

export const TIMESTAMP_HEADER = "X-Frontdesk-Timestamp";
export const SIGNATURE_HEADER = "X-Frontdesk-Signature";

/**
 * Signs a request to the API. The signature covers a timestamp, the method, the path and
 * the exact body, and must match `frontdesk.channels.signing` in the backend byte for byte.
 */
export function sign(
  secret: string,
  at: Date,
  method: string,
  path: string,
  body: string,
): Record<string, string> {
  const timestamp = Math.floor(at.getTime() / 1000).toString();
  const digest = createHmac("sha256", secret)
    .update(`${timestamp}.${method.toUpperCase()}.${path}.`)
    .update(body)
    .digest("hex");
  return { [TIMESTAMP_HEADER]: timestamp, [SIGNATURE_HEADER]: `sha256=${digest}` };
}
