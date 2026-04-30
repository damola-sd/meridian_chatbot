"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { API_BASE } from "@/lib/api";
import type { ChatMessage } from "@/components/Message";

const SESSION_STORAGE_KEY = "meridian_session_id";

interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string;
  sendMessage: (text: string) => Promise<void>;
  clearMessages: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  // Session ID — generated once per browser session, persisted across page refreshes
  const [sessionId] = useState<string>(() => {
    if (typeof window === "undefined") return uuidv4();
    const stored = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (stored) return stored;
    const id = uuidv4();
    sessionStorage.setItem(SESSION_STORAGE_KEY, id);
    return id;
  });

  // Guard against sending while already streaming
  const isStreamingRef = useRef(false);

  const sendMessage = useCallback(
    async (text: string) => {
      if (isStreamingRef.current) return;

      // Append user message immediately (optimistic)
      const userMsg: ChatMessage = {
        id: uuidv4(),
        role: "user",
        content: text,
      };

      // Placeholder for the assistant reply — filled in as chunks arrive
      const assistantMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content: "",
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      isStreamingRef.current = true;

      try {
        const response = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: text }),
        });

        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          // Append raw bytes to buffer and process all complete SSE lines
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          // Keep the last (possibly incomplete) line in the buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data:")) continue;

            const payload = trimmed.slice(5).trim();
            if (payload === "[DONE]") {
              setIsStreaming(false);
              isStreamingRef.current = false;
              return;
            }

            try {
              const data = JSON.parse(payload);

              if (data.error) {
                // Replace empty assistant placeholder with the error message
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, content: `Sorry, something went wrong. Please try again.` }
                      : m
                  )
                );
                return;
              }

              if (data.text) {
                // Append chunk to the assistant message in place
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, content: m.content + data.text }
                      : m
                  )
                );
              }
            } catch {
              // Malformed JSON chunk — skip silently
            }
          }
        }
      } catch (err) {
        console.error("Chat error:", err);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content:
                    "I'm having trouble connecting right now. Please check your connection and try again.",
                }
              : m
          )
        );
      } finally {
        setIsStreaming(false);
        isStreamingRef.current = false;
      }
    },
    [sessionId]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  // Warn in dev if API base is not configured
  useEffect(() => {
    if (process.env.NODE_ENV === "development" && !process.env.NEXT_PUBLIC_API_URL) {
      console.warn(
        "[useChat] NEXT_PUBLIC_API_URL is not set — falling back to http://localhost:8000"
      );
    }
  }, []);

  return { messages, isStreaming, sessionId, sendMessage, clearMessages };
}
