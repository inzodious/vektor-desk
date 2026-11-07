import { useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { accountLabel } from '../live/context.js';

const NO_COPY = new Set(['Account', 'Order type', 'Time in force']);

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function Ticket({ ticket }) {
  const [copied, setCopied] = useState(null);
  const copy = async (key, text) => {
    const ok = await copyText(text);
    setCopied(ok ? key : 'fail');
    setTimeout(() => setCopied(null), 1600);
  };
  return (
    <div className="ticket" data-stamp={ticket.stamp}>
      <span className={`stamp ${(ticket.stamp || '').toLowerCase()}`}>{ticket.stamp}</span>
      <dl className="tk">
        {ticket.fields.map((f) => {
          const shown = f.label === 'Account' ? accountLabel(f.value) : f.value;
          return (
            <div className="tk-row" key={f.label}>
              <dt>{f.label}</dt>
              <dd>{shown}</dd>
              {NO_COPY.has(f.label) ? (
                <span />
              ) : (
                <button type="button" className="copy" aria-label={`Copy ${f.label.toLowerCase()}`} title={copied === f.label ? 'Copied' : `Copy ${f.label.toLowerCase()}`} onClick={() => copy(f.label, f.value)}>
                  <Icon name={copied === f.label ? 'check' : 'copy'} />
                </button>
              )}
            </div>
          );
        })}
      </dl>
      <div className="tk-foot">
        <button type="button" className="btn sm ghost" onClick={() => copy('all', ticket.text)}>
          <Icon name={copied === 'all' ? 'check' : 'copy'} />
          {copied === 'all' ? 'Copied' : 'Copy the whole ticket'}
        </button>
        <span className="muted" role="status" style={{ fontSize: 12 }}>
          {copied === 'fail' ? "The browser blocked the clipboard. Select the text instead." : ''}
        </span>
      </div>
    </div>
  );
}
