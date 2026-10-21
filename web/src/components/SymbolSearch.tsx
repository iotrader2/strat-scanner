import { sanitizeWithCaret, SYMBOL_SEARCH_MAX } from "../symbolSearch";

/** Ticker-only search box: uppercases and strips non-ticker characters as you type, keeping the caret in place. */
export function SymbolSearch({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="search-field">
      <input
        className="input search"
        placeholder="Symbol"
        aria-label="Search by symbol"
        value={value}
        maxLength={SYMBOL_SEARCH_MAX}
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        onChange={(e) => {
          // Write the cleaned text and caret straight into the input: React then finds the DOM already matching
          // and leaves the caret alone, even when a stripped keystroke leaves the value unchanged.
          const el = e.target;
          const next = sanitizeWithCaret(el.value, el.selectionStart);
          if (el.value !== next.value) {
            el.value = next.value;
            el.setSelectionRange(next.caret, next.caret);
          }
          onChange(next.value);
        }}
      />
      {value && (
        <button type="button" className="search-clear" aria-label="Clear search" onClick={() => onChange("")}>
          X
        </button>
      )}
    </div>
  );
}
