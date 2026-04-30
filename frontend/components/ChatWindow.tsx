"use client";

import { useEffect, useRef, useState } from "react";
import Message, { type ChatMessage } from "./Message";
import QuickActions from "./QuickActions";

interface ChatWindowProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string) => void;
}

export default function ChatWindow({ messages, isStreaming, onSend }: ChatWindowProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const hasMessages = messages.length > 0;

  // Auto-scroll to newest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    onSend(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (prompt: string) => {
    if (isStreaming) return;
    onSend(prompt);
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {!hasMessages && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center pb-8">
            <div className="w-14 h-14 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-2xl font-bold shadow-md">
              A
            </div>
            <div>
              <p className="font-semibold text-gray-800">Hi, I'm Aria!</p>
              <p className="text-sm text-gray-500 mt-1 max-w-xs">
                I can help you browse products, check your orders, or place a new order.
              </p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <Message
            key={msg.id}
            message={msg}
            isStreaming={isStreaming && i === messages.length - 1 && msg.role === "assistant"}
          />
        ))}

        {/* Typing indicator — shown while waiting for first token */}
        {isStreaming && messages[messages.length - 1]?.role === "user" && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-xs font-bold shadow-sm flex-shrink-0">
              A
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
              <span className="inline-flex gap-1 items-center">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Quick actions — only shown before the first message */}
      {!hasMessages && (
        <QuickActions onSelect={handleQuickAction} disabled={isStreaming} />
      )}

      {/* Input bar */}
      <div className="border-t border-gray-200 bg-white px-4 py-3">
        <div className="flex items-end gap-2 bg-gray-50 rounded-2xl border border-gray-200 px-4 py-2 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={isStreaming ? "Aria is typing…" : "Type a message…"}
            className="
              flex-1 bg-transparent text-sm text-gray-800 placeholder-gray-400
              resize-none outline-none max-h-32 leading-relaxed
              disabled:cursor-not-allowed
            "
            style={{ height: "24px", overflowY: "hidden" }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "24px";
              el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
              el.style.overflowY = el.scrollHeight > 128 ? "auto" : "hidden";
            }}
          />
          <button
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
            aria-label="Send message"
            className="
              flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
              bg-blue-600 text-white
              hover:bg-blue-700 active:scale-95
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all duration-150
            "
          >
            <svg className="w-4 h-4 rotate-90" fill="currentColor" viewBox="0 0 24 24">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          </button>
        </div>
        <p className="text-[10px] text-gray-400 text-center mt-2">
          Press Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
