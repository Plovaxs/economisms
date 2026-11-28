import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { Command } from "./commands";
import { rank } from "./fuzzy";
import { useDialog } from "./useDialog";

interface Props {
  open: boolean;
  onClose: () => void;
  commands: Command[];
}

// The command palette: a modal combobox over every action in the app. Up/Down move, Enter runs,
// Esc closes and focus returns to where it came from. Typing filters with the fuzzy matcher.
export function CommandPalette({ open, onClose, commands }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  useDialog(open, onClose, dialog);

  const results = useMemo(() => rank(query, commands, 30), [query, commands]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      input.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, listId]);

  if (!open) return null;

  const run = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="shell-panel w-full max-w-xl overflow-hidden rounded-2xl border border-white/15 bg-base-elevated shadow-glass"
      >
        <input
          ref={input}
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={results.length ? `${listId}-${active}` : undefined}
          aria-autocomplete="list"
          aria-label="Type a command, a page or a model"
          placeholder="Type a command, a page or a model…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, Math.max(results.length - 1, 0)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Home") {
              e.preventDefault();
              setActive(0);
            } else if (e.key === "End") {
              e.preventDefault();
              setActive(Math.max(results.length - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              run(results[active]);
            }
          }}
          className="w-full border-b border-white/10 bg-transparent px-5 py-4 text-base text-slate-50 placeholder:text-slate-400 focus:outline-none"
        />
        <ul id={listId} role="listbox" aria-label="Results" className="max-h-[50vh] overflow-y-auto p-2">
          {results.map((c, index) => (
            <li
              key={c.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              onMouseMove={() => setActive(index)}
              onClick={() => run(c)}
              className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm ${
                index === active ? "bg-accent-a/10 text-slate-50 ring-1 ring-inset ring-accent-a/60" : "text-slate-300"
              }`}
            >
              <span>
                <span className="mr-2 text-xs uppercase tracking-wider text-slate-500">{c.group}</span>
                {c.label}
              </span>
              {c.hint && <kbd className="rounded border border-white/15 px-1.5 text-xs text-slate-400">{c.hint}</kbd>}
            </li>
          ))}
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-slate-400">Nothing matches “{query}”.</li>}
        </ul>
        <p className="border-t border-white/10 px-4 py-2 text-xs text-slate-400">
          Up and Down to choose, Enter to run, Esc to close. Press ? anywhere for all shortcuts.
        </p>
        <div aria-live="polite" className="sr-only-live">
          {results.length} results
        </div>
      </div>
    </div>
  );
}
