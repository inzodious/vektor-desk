import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { LabHero } from '../lab/parts.jsx';
import { etStamp, plural } from '../lib/format.js';
import { BOARD_VIEW, readBoards, removeBoard } from '../lib/lab.js';

export default function Boards() {
  const [list, setList] = useState(() => readBoards());
  return (
    <>
      <LabHero
        area="research"
        kicker="Saved boards"
        title="Saved boards"
        big={
          <>
            <b>{list.length}</b>
            <span className="muted">{list.length === 1 ? 'board' : 'boards'} pinned with their slicers</span>
          </>
        }
      />
      <section className="grid">
        <div className="card c8 top" data-testid="boards">
          <div className="card-head">
            <span className="tag">Boards</span>
            <span className="chip">{list.length ? plural(list.length, 'board') : 'None yet'}</span>
          </div>
          {list.length ? (
            <div className="rows">
              {list.map((b) => {
                const path = b.path.split('?')[0];
                return (
                  <div className="row still" key={b.id} data-board={b.id}>
                    <span className="l">
                      <span className="desk-ico sm">
                        <Icon name="pin" />
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>
                          <Link to={b.path}>{b.name}</Link>
                        </b>
                        <small>
                          {BOARD_VIEW[path] || 'Board'} · saved {etStamp(b.saved_at)}
                        </small>
                      </span>
                    </span>
                    <button className="btn sm ghost" type="button" aria-label={`Remove ${b.name}`} onClick={() => setList(removeBoard(b.id))}>
                      <Icon name="x" />
                      Remove
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="empty-hint">No boards yet. Set up a Compare, Risk or My habits view the way you like it, then press Save as a board.</p>
          )}
        </div>
        <div className="stack c4">
          <div className="card">
            <div className="card-head">
              <span className="tag mint">How boards work</span>
            </div>
            <div className="rule">
              <Icon name="pin" />
              <span>
                <b>A board is a view plus its slicers</b>
                <small>Items, window and filters come back exactly as saved. The numbers are always today&apos;s.</small>
              </span>
              <span />
            </div>
            <div className="rule">
              <Icon name="info" />
              <span>
                <b>Kept in this browser</b>
                <small>Boards live on the device that saved them, so the phone and the desktop keep their own.</small>
              </span>
              <span />
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
