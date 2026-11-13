export function About({ label = 'How to read this', testid = 'about', children }) {
  return (
    <details className="about" data-testid={testid}>
      <summary>{label}</summary>
      <div className="about-body">{children}</div>
    </details>
  );
}
