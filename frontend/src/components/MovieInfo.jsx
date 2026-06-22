import { fmtBitrate, fmtResolution, fmtRuntime, fmtSize } from "../format.js";

// Compact technical readout for a media file, reused in the wizard and elsewhere.
export default function MovieInfo({ media }) {
  if (!media) return null;
  const rows = [
    ["Runtime", fmtRuntime(media.duration_seconds)],
    ["Resolution", fmtResolution(media)],
    ["Aspect ratio", media.aspect_ratio || "—"],
    ["Video codec", media.video_codec || "—"],
    ["HDR", media.is_hdr10 ? "HDR10" : "SDR"],
    ["Audio", media.audio_format || media.audio_summary || "—"],
    ["File size", fmtSize(media.file_size)],
    ["Bitrate", fmtBitrate(media.bitrate)],
  ];
  return (
    <div className="card" style={{ marginTop: 8 }}>
      <div className="muted" style={{ marginBottom: 6 }}>Movie info</div>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="muted" style={{ width: 130 }}>{k}</td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
