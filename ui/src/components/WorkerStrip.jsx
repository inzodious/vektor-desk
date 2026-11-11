import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from './Icon.jsx';
import { workerStrip } from '../lib/workers.js';

const KEY = 'desk.workers.hidden';

function readHidden() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function WorkerStrip({ data }) {
  const [hidden, setHidden] = useState(readHidden);
  const strip = workerStrip(data);
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
    <section className="mem-strip" role="status" data-testid="worker-strip">
      <Icon name="clock" />
      <p>
        <b>{strip.head}.</b> {strip.line}
      </p>
      <span className="mem-strip-acts">
        <Link className="link" to={strip.to} data-testid="worker-strip-open">
          {strip.label}
        </Link>
        <button className="link" type="button" onClick={hide} data-testid="worker-strip-hide">
          Hide
        </button>
      </span>
    </section>
  );
}
