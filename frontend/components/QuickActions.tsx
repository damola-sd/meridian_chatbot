"use client";

const QUICK_ACTIONS = [
  { label: "Browse products",   prompt: "What products do you carry?" },
  { label: "Search monitors",   prompt: "Show me your monitors" },
  { label: "My orders",         prompt: "I'd like to check my order history" },
  { label: "Place an order",    prompt: "I'd like to place an order" },
];

interface QuickActionsProps {
  onSelect: (prompt: string) => void;
  disabled?: boolean;
}

export default function QuickActions({ onSelect, disabled = false }: QuickActionsProps) {
  return (
    <div className="px-4 pb-3">
      <p className="text-xs text-gray-400 mb-2 font-medium">Quick actions</p>
      <div className="flex flex-wrap gap-2">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => onSelect(action.prompt)}
            disabled={disabled}
            className="
              px-3 py-1.5 rounded-full text-xs font-medium border
              bg-white text-blue-600 border-blue-200
              hover:bg-blue-50 hover:border-blue-400
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-colors duration-150
            "
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
