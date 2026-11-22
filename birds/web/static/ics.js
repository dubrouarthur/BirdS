// .ics calendar file built in the browser (RFC 5545): METHOD:PUBLISH, no ATTENDEE, nothing sent anywhere.

const enc = new TextEncoder();

/** Escape a TEXT value (backslash, semicolon, comma, newline). */
export function icsEscape(text) {
  return String(text ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

/** Fold a content line at 75 octets (CRLF + space), never inside a UTF-8 character. */
export function icsFold(line) {
  const out = [];
  let cur = "";
  let size = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > (out.length ? 74 : 75)) {
      out.push(cur);
      cur = "";
      size = 0;
    }
    cur += ch;
    size += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

const pad = (n, w = 2) => String(n).padStart(w, "0");
export const utcStamp = (d) =>
  `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;

/** Minutes east of UTC of a time zone at an instant (Intl only, no library). */
export function tzOffset(ms, tz) {
  try {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: tz,
        hourCycle: "h23",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
        .formatToParts(new Date(ms))
        .map((p) => [p.type, p.value]),
    );
    const asUtc = Date.UTC(
      +parts.year,
      +parts.month - 1,
      +parts.day,
      +parts.hour % 24,
      +parts.minute,
      +parts.second,
    );
    return Math.round((asUtc - ms) / 60000);
  } catch {
    return 0;
  }
}

/** The instant of a wall-clock date ("2026-11-26") and time ("14:00") in a time zone. */
export function zonedInstant(dateStr, timeStr, tz) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const [hh, mm] = (timeStr || "00:00").split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  let ms = guess - tzOffset(guess, tz) * 60000;
  ms = guess - tzOffset(ms, tz) * 60000; // second pass: right across a DST change
  return new Date(ms);
}

/** The text of an .ics file for one event. `ev`: {title, date, start, end, endDate, allDay, tz, location, description}. */
export function buildIcs(ev, { uid, now = new Date() } = {}) {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Bird//FR",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${uid || (globalThis.crypto?.randomUUID?.() ?? String(now.getTime()))}@bird`,
    `DTSTAMP:${utcStamp(now)}`,
  ];
  if (ev.allDay) {
    const next = new Date(
      Date.UTC(...ev.date.split("-").map((v, i) => (i === 1 ? +v - 1 : +v))) +
        86400000,
    );
    lines.push(`DTSTART;VALUE=DATE:${ev.date.replaceAll("-", "")}`);
    lines.push(
      `DTEND;VALUE=DATE:${next.toISOString().slice(0, 10).replaceAll("-", "")}`,
    );
  } else {
    lines.push(`DTSTART:${utcStamp(zonedInstant(ev.date, ev.start, ev.tz))}`);
    lines.push(
      `DTEND:${utcStamp(zonedInstant(ev.endDate || ev.date, ev.end, ev.tz))}`,
    );
  }
  lines.push(`SUMMARY:${icsEscape(ev.title)}`);
  if (ev.location) lines.push(`LOCATION:${icsEscape(ev.location)}`);
  if (ev.description) lines.push(`DESCRIPTION:${icsEscape(ev.description)}`);
  lines.push("END:VEVENT", "END:VCALENDAR");
  return lines.map(icsFold).join("\r\n") + "\r\n";
}

/** "reunion-avec-paul-2026-12-03.ics": ASCII, at most 60 characters before the extension. */
export function icsName(title, date) {
  const slug = String(title || "evenement")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/g, "");
  return `${slug || "evenement"}-${date}.ics`;
}
