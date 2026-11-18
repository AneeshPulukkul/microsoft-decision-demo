export default function TicketForm({ text, onChange, onRun, loading, samples }) {
  const disabled = loading || !text.trim();

  function handleSubmit(event) {
    event.preventDefault();
    onRun(text);
  }

  function handleKeyDown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      onRun(text);
    }
  }

  return (
    <section className="panel">
      <form onSubmit={handleSubmit}>
        <label htmlFor="ticket">Customer ticket</label>
        <textarea
          id="ticket"
          rows={5}
          maxLength={8000}
          value={text}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Paste a support message, or pick a sample below."
        />
        <div className="row">
          <div className="chips">
            {(samples || []).map((sample) => (
              <button
                key={sample.label}
                type="button"
                className="chip-btn"
                onClick={() => onRun(sample.text)}
                disabled={loading}
              >
                {sample.label}
              </button>
            ))}
          </div>
          <button type="submit" className="primary" disabled={disabled}>
            {loading ? "Deciding..." : "Decide"}
          </button>
        </div>
        <p className="hint">Ctrl+Enter to submit. The model returns probabilities, not generated text.</p>
      </form>
    </section>
  );
}
