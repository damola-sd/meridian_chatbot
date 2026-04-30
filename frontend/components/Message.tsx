"use client";

import ReactMarkdown from "react-markdown";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface MessageProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export default function Message({ message, isStreaming = false }: MessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div className="flex-shrink-0 mt-1">
        {isUser ? (
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-semibold">
            You
          </div>
        ) : (
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-xs font-bold shadow-sm">
            A
          </div>
        )}
      </div>

      {/* Bubble */}
      <div
        className={`
          max-w-[75%] rounded-2xl px-4 py-3 shadow-sm
          ${isUser
            ? "bg-blue-600 text-white rounded-tr-sm"
            : "bg-white text-gray-800 rounded-tl-sm border border-gray-100"
          }
        `}
      >
        {isUser ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-headings:text-gray-900 prose-strong:text-gray-900">
            <ReactMarkdown>{message.content}</ReactMarkdown>
            {isStreaming && (
              <span className="inline-flex gap-0.5 ml-1 align-middle">
                <span className="w-1 h-1 bg-blue-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1 h-1 bg-blue-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1 h-1 bg-blue-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
