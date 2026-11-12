import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { memoryStrip } from '../lib/memory.js';
import { useStart } from '../start/context.js';

const KEY = 'desk.memory.hidden';

function readHidden() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function MemoryStrip() {
  const { memory } = useStart();
  const [hidden, setHidden] = useState(readHidden);
  const detail = useApi(memory?.low_memory ? '/api/memory' : null, { every: 60000 });
  const strip = memoryStrip(memory, detail.data);
  if (!strip || hidden === strip.key) return null;
  const hide = () => {
    setHidden(strip.key);
    try {
      window.localStorage.setItem(KEY, strip.key);
    } catch {
      return;
    }
  };
  return (
    <section className={`mem-strip ${strip.tone}`} role="status" data-testid="memory-strip" data-tone={strip.tone}>
      <Icon name="info" />
      <p>
        <b>{strip.head}.</b> {strip.line}
      </p>
      <span className="mem-strip-acts">
        <Link className="link" to={strip.to} data-testid="memory-strip-open">
          {strip.label}
        </Link>
        <button className="link" type="button" onClick={hide} data-testid="memory-strip-hide">
          Hide
        </button>
      </span>
    </section>
  );
}
