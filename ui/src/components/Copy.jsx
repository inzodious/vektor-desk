import { useState } from 'react';
import { Icon } from './Icon.jsx';

export function Copy({ text, label, testid }) {
  const [state, setState] = useState(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('failed');
    }
  };
  return (
    <span className="key-acts">
      <button className="btn sm" type="button" onClick={copy} data-testid={testid}>
        <Icon name={state === 'copied' ? 'check' : 'copy'} />
        {state === 'copied' ? 'Copied' : label}
      </button>
      {state === 'failed' ? <small className="job-note refused">Couldn’t copy. Select it and copy by hand.</small> : null}
    </span>
  );
}
