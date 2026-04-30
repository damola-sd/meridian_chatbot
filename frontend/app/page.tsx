"use client";

import { useChat } from "@/hooks/useChat";
import ChatWindow from "@/components/ChatWindow";

export default function Home() {
  const { messages, isStreaming, sendMessage, clearMessages } = useChat();

  return (
    <main className="flex flex-col h-screen max-w-2xl mx-auto shadow-xl">
      {/* Header */}
      <header className="flex items-center justify-between gap-3 bg-white border-b border-gray-200 px-5 py-3 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white font-bold text-sm shadow-sm">
            A
          </div>
          <div>
            <p className="font-semibold text-gray-900 text-sm leading-tight">Aria</p>
            <p className="text-xs text-gray-500 leading-tight">Meridian Electronics Support</p>
          </div>
          <span className="flex items-center gap-1 ml-1">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <span className="text-xs text-green-600 font-medium">Online</span>
          </span>
        </div>

        {/* New conversation button — only shown when there are messages */}
        {messages.length > 0 && (
          <button
            onClick={clearMessages}
            title="Start new conversation"
            className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New chat
          </button>
        )}
      </header>

      {/* Chat body */}
      <ChatWindow
        messages={messages}
        isStreaming={isStreaming}
        onSend={sendMessage}
      />

      {/* Footer */}
      <footer className="bg-white border-t border-gray-100 px-5 py-2 flex-shrink-0">
        <p className="text-[10px] text-center text-gray-400">
          Meridian Electronics · AI support powered by GPT-4o-mini ·{" "}
          <a href="mailto:support@meridianelectronics.com" className="hover:text-blue-500 transition-colors">
            support@meridianelectronics.com
          </a>
        </p>
      </footer>
    </main>
  );
}
