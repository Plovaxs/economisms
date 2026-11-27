import { useEffect, useRef } from "react";

import { SHORTCUTS } from "./commands";
import { useDialog } from "./useDialog";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ShortcutsDialog({ open, onClose }: Props) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useDialog(open, onClose, dialog);
  useEffect(() => {
    if (open) close.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="shell-panel w-full max-w-lg rounded-2xl border border-white/15 bg-base-elevated p-6 shadow-glass"
      >
        <div className="flex items-center justify-between">
          <h2 id="shortcuts-title" className="text-lg font-semibold text-slate-50">
            Keyboard shortcuts
          </h2>
          <button
            ref={close}
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/15 px-3 py-1 text-sm text-slate-200 hover:bg-white/10"
          >
            Close
          </button>
        </div>
        <dl className="mt-4 grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-4 gap-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="contents">
              <dt>
                <kbd className="rounded border border-white/15 px-1.5 py-0.5 text-xs text-slate-200">{s.keys}</kbd>
              </dt>
              <dd className="text-slate-300">{s.does}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
