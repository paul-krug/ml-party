import { ReactNode, useEffect, useState } from "react";
import { ArtifactRec, api } from "../../api";

export type Group =
  "boards" | "images" | "audio" | "video" | "tensors" | "checkpoints" | "text" | "other";

const EXT_GROUP: Record<string, Group> = {
  html: "boards", htm: "boards",
  png: "images", jpg: "images", jpeg: "images", gif: "images", webp: "images",
  svg: "images", bmp: "images",
  wav: "audio", mp3: "audio", flac: "audio", ogg: "audio", m4a: "audio",
  mp4: "video", webm: "video", mov: "video", mkv: "video",
  npy: "tensors", npz: "tensors",
  pt: "checkpoints", pth: "checkpoints", ckpt: "checkpoints", safetensors: "checkpoints",
  txt: "text", log: "text", md: "text", json: "text", yaml: "text", yml: "text",
  csv: "text", tsv: "text", py: "text", cfg: "text", ini: "text", toml: "text",
};

const EXT_MIME: Record<string, string> = {
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif",
  webp: "image/webp", svg: "image/svg+xml", bmp: "image/bmp",
  wav: "audio/wav", mp3: "audio/mpeg", flac: "audio/flac", ogg: "audio/ogg", m4a: "audio/mp4",
  mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime",
};

export function ext(path: string): string {
  return (path.split(".").pop() ?? "").toLowerCase();
}

export function classify(a: ArtifactRec): Group {
  const mt = a.media_type ?? "";
  if (mt === "text/html") return "boards";
  if (mt.startsWith("image/")) return "images";
  if (mt.startsWith("audio/")) return "audio";
  if (mt.startsWith("video/")) return "video";
  if (mt.startsWith("text/")) return "text";
  return EXT_GROUP[ext(a.original_path)] ?? "other";
}

export function mime(a: ArtifactRec): string {
  return a.media_type || EXT_MIME[ext(a.original_path)] || "application/octet-stream";
}

export function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

export function fmtBytes(n: number): string {
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(2)} GiB`;
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MiB`;
  return `${(n / 1024).toFixed(1)} KiB`;
}

function TextPreview({ a }: { a: ArtifactRec }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    setText(null);
    setErr("");
    fetch(api.artifactInlineUrl(a.sha256, basename(a.original_path), "text/plain"))
      .then(async (r) => {
        if (!r.ok) throw new Error(r.statusText);
        const raw = await (a.size_bytes > 262144
          ? r.body!.getReader().read().then((c) => new TextDecoder().decode(c.value))
          : r.text());
        setText(raw.slice(0, 200000));
      })
      .catch((e) => setErr(String(e)));
  }, [a.sha256]);
  if (err) return <div className="muted small">could not load: {err}</div>;
  if (text == null) return <div className="muted small">loading…</div>;
  return (
    <>
      <pre style={{ maxHeight: "50vh", overflow: "auto" }}>{text}</pre>
      {(a.size_bytes > 200000) && <div className="muted small">truncated preview</div>}
    </>
  );
}

export default function Viewer({ a, tensor }: {
  a: ArtifactRec;
  tensor: (sha256: string) => ReactNode;
}) {
  const group = classify(a);
  const name = basename(a.original_path);
  const url = api.artifactInlineUrl(a.sha256, name, mime(a));
  switch (group) {
    case "boards":
      return (
        <div>
          <p className="small" style={{ marginTop: 0 }}>
            Custom HTML board — renders sandboxed (own origin, read-only API
            access, no external hosts).
          </p>
          <a href={`#/board/${a.sha256}?name=${encodeURIComponent(name)}`}>
            <button className="boardopen">open board ⇗</button>
          </a>
        </div>
      );
    case "images":
      return <img src={url} alt={name} style={{ maxWidth: "100%", maxHeight: "60vh" }} />;
    case "audio":
      return <audio controls src={url} style={{ width: "100%" }} />;
    case "video":
      return <video controls src={url} style={{ maxWidth: "100%", maxHeight: "60vh" }} />;
    case "text":
      return <TextPreview a={a} />;
    case "tensors":
      return <>{tensor(a.sha256)}</>;
    case "checkpoints":
      return (
        <div className="muted small">
          serialized checkpoint — not viewable in the browser (loading it requires the
          training framework); download to inspect
        </div>
      );
    default:
      return <div className="muted small">no viewer for this file type — download to inspect</div>;
  }
}
