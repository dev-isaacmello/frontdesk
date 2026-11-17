"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { type ChatMessage, chatStore, EMPTY } from "./chat-store";

export type { ChatMessage };

export type ChatState = {
  messages: ChatMessage[];
  /** The agent is working on a reply. */
  waiting: boolean;
  /** The reply stream dropped and the browser is trying again. */
  reconnecting: boolean;
  send: (text: string) => void;
  retry: (id: string) => void;
};

export function useChat(tenant: string): ChatState {
  const store = useMemo(() => chatStore(tenant), [tenant]);
  const { conversationId, messages } = useSyncExternalStore(store.subscribe, store.get, () => EMPTY);
  const [waiting, setWaiting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    if (!conversationId) {
      return;
    }
    const query = new URLSearchParams({ conversation_id: conversationId });
    const lastReply = store.get().messages.findLast((message) => message.author === "agent");
    if (lastReply) {
      query.set("after", lastReply.id);
    }
    const stream = new EventSource(`/api/chat/${tenant}/events?${query}`);
    stream.onopen = () => setReconnecting(false);
    stream.onerror = () => setReconnecting(true);
    stream.onmessage = (event) => {
      const { text } = JSON.parse(event.data) as { text: string };
      setWaiting(false);
      store.update((current) =>
        current.messages.some((message) => message.id === event.lastEventId)
          ? current
          : {
              ...current,
              messages: [...current.messages, { id: event.lastEventId, author: "agent", text }],
            },
      );
    };
    return () => stream.close();
  }, [conversationId, store, tenant]);

  const deliver = useCallback(
    async (message: ChatMessage) => {
      const mark = (delivery: ChatMessage["delivery"], conversation?: string) =>
        store.update((current) => ({
          conversationId: conversation ?? current.conversationId,
          messages: current.messages.map((each) =>
            each.id === message.id ? { ...each, delivery } : each,
          ),
        }));
      try {
        const response = await fetch(`/api/chat/${tenant}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_id: message.id, text: message.text }),
        });
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const { conversation_id } = (await response.json()) as { conversation_id: string };
        mark(undefined, conversation_id);
        setWaiting(true);
      } catch {
        mark("failed");
      }
    },
    [store, tenant],
  );

  const send = useCallback(
    (text: string) => {
      const message: ChatMessage = {
        id: crypto.randomUUID(),
        author: "customer",
        text,
        delivery: "sending",
      };
      store.update((current) => ({ ...current, messages: [...current.messages, message] }));
      void deliver(message);
    },
    [deliver, store],
  );

  const retry = useCallback(
    (id: string) => {
      const message = store.get().messages.find((each) => each.id === id);
      if (!message) {
        return;
      }
      store.update((current) => ({
        ...current,
        messages: current.messages.map((each) =>
          each.id === id ? { ...each, delivery: "sending" } : each,
        ),
      }));
      // The same id goes again, so a message that did arrive is not answered twice.
      void deliver(message);
    },
    [deliver, store],
  );

  return { messages, waiting, reconnecting, send, retry };
}
