export type ChatMessage = {
  id: string;
  author: "customer" | "agent";
  text: string;
  delivery?: "sending" | "failed";
};

export type Conversation = { conversationId: string | null; messages: ChatMessage[] };

export type ChatStore = {
  get: () => Conversation;
  subscribe: (listener: () => void) => () => void;
  update: (change: (current: Conversation) => Conversation) => void;
};

export const EMPTY: Conversation = { conversationId: null, messages: [] };

const stores = new Map<string, ChatStore>();

/**
 * The conversation of one tenant, kept in the tab's session storage so that it survives
 * a reload. It is an external store because it lives outside React and outlives renders.
 */
export function chatStore(tenant: string): ChatStore {
  const existing = stores.get(tenant);
  if (existing) {
    return existing;
  }
  const key = `frontdesk:chat:${tenant}`;
  const listeners = new Set<() => void>();
  let state: Conversation | undefined;

  const get = () => (state ??= load(key));
  const store: ChatStore = {
    get,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    update(change) {
      state = change(get());
      window.sessionStorage.setItem(key, JSON.stringify(state));
      listeners.forEach((listener) => listener());
    },
  };
  stores.set(tenant, store);
  return store;
}

function load(key: string): Conversation {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Conversation) : EMPTY;
  } catch {
    return EMPTY;
  }
}
