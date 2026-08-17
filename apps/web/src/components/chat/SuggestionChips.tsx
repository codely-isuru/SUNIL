"use client";

export interface SuggestionChipsProps {
  suggestions: string[];
  onPick: (text: string) => void;
}

/**
 * Empty-state only (M1_CHAT_SPEC.md §3). Clicking a chip populates the
 * composer with that exact text and focuses it — it never auto-sends.
 */
export function SuggestionChips({ suggestions, onPick }: SuggestionChipsProps) {
  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-wrap justify-center gap-2">
      {suggestions.map((text) => (
        <button
          key={text}
          type="button"
          onClick={() => onPick(text)}
          className="min-h-11 rounded-full border border-border-accent bg-surface px-4 py-2 font-mono-body text-small text-text-secondary transition-colors duration-fast ease-standard hover:border-border-strong hover:bg-surface-raised hover:text-text-primary"
        >
          {text}
        </button>
      ))}
    </div>
  );
}
