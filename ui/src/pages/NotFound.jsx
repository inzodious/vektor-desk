import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';

export default function NotFound() {
  return <Hero kicker="Off course" title="Lost in orbit" art="bridge" sub="That page isn't on the desk." foot={<Link className="btn sm" to="/">Back to the Bridge</Link>} />;
}
