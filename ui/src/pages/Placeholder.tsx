export default function Placeholder({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h1>{title}</h1>
      <div className="panel">
        <p style={{ margin: 0 }}>
          <span className="tag">planned</span> {text}
        </p>
      </div>
    </div>
  );
}
