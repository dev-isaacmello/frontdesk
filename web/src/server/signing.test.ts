import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { sign, SIGNATURE_HEADER, TIMESTAMP_HEADER } = await import("./signing");

describe("sign", () => {
  // The expected values were produced by `frontdesk.channels.signing.sign` in the backend
  // for the same inputs. If either side changes, the API starts answering 401.
  it("ING-1 produces the signature the API verifies", () => {
    const headers = sign(
      "a-test-secret",
      new Date("2026-11-18T10:00:00Z"),
      "post",
      "/channels/webchat/navalha/messages?x=1",
      '{"text":"olá, tudo bem?"}',
    );

    expect(headers[TIMESTAMP_HEADER]).toBe("1794996000");
    expect(headers[SIGNATURE_HEADER]).toBe("sha256=961a58319721a72d9a9702c20be3dfee99ef9c5b041876c175c7f0963d422ca8");
  });

  it("ING-1 changes when the body changes", () => {
    const at = new Date("2026-11-18T10:00:00Z");
    const one = sign("a-test-secret", at, "POST", "/p", '{"text":"oi"}');
    const other = sign("a-test-secret", at, "POST", "/p", '{"text":"oi!"}');

    expect(one[SIGNATURE_HEADER]).not.toBe(other[SIGNATURE_HEADER]);
  });
});
