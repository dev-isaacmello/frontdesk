/** How the panel writes money, durations and times. Every time is shown in São Paulo. */

const ZONE = "America/Sao_Paulo";
const LOCALE = "pt-BR";
const DAY_MS = 24 * 60 * 60 * 1000;

const dayKeyFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const clockFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const weekdayFormat = new Intl.DateTimeFormat(LOCALE, { timeZone: ZONE, weekday: "long" });
const dayMonthFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONE,
  day: "2-digit",
  month: "2-digit",
});
const dayMonthYearFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});
const longDayFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONE,
  day: "numeric",
  month: "long",
});
const wholeFormat = new Intl.NumberFormat(LOCALE);

function valid(iso: string): Date | undefined {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

/** The calendar day in São Paulo, as YYYY-MM-DD. */
export function dayKey(at: Date): string {
  return dayKeyFormat.format(at);
}

/** How many calendar days in São Paulo `at` is before `now`. Negative when it is ahead. */
function daysAgo(at: Date, now: Date): number {
  return Math.round((Date.parse(dayKey(now)) - Date.parse(dayKey(at))) / DAY_MS);
}

function sameYear(at: Date, now: Date): boolean {
  return dayKey(at).slice(0, 4) === dayKey(now).slice(0, 4);
}

/** "quinta", "sábado": the weekday as people say it, without "-feira". */
function weekday(at: Date): string {
  return weekdayFormat.format(at).replace("-feira", "");
}

/** 14:00 */
export function formatClock(iso: string): string {
  const at = valid(iso);
  return at ? clockFormat.format(at) : "";
}

/** The short time of a row in a list: 22:09 today, then "ontem", the weekday, the date. */
export function formatListTime(iso: string, now: Date): string {
  const at = valid(iso);
  if (!at) {
    return "";
  }
  const ago = daysAgo(at, now);
  if (ago === 0) {
    return clockFormat.format(at);
  }
  if (ago === 1) {
    return "ontem";
  }
  if (ago > 1 && ago < 7) {
    return weekday(at);
  }
  return sameYear(at, now) ? dayMonthFormat.format(at) : dayMonthYearFormat.format(at);
}

/** quinta 19/11 às 14:00 */
export function formatDayAndTime(iso: string): string {
  const at = valid(iso);
  return at ? `${weekday(at)} ${dayMonthFormat.format(at)} às ${clockFormat.format(at)}` : "";
}

/** A moment as part of a sentence: "hoje às 22:09", "ontem às 09:30", "quinta 19/11 às 14:00". */
export function formatMoment(iso: string, now: Date): string {
  const at = valid(iso);
  if (!at) {
    return "";
  }
  const ago = daysAgo(at, now);
  if (ago === 0) {
    return `hoje às ${clockFormat.format(at)}`;
  }
  if (ago === 1) {
    return `ontem às ${clockFormat.format(at)}`;
  }
  if (ago === -1) {
    return `amanhã às ${clockFormat.format(at)}`;
  }
  const date = sameYear(at, now) ? dayMonthFormat.format(at) : dayMonthYearFormat.format(at);
  return `${weekday(at)} ${date} às ${clockFormat.format(at)}`;
}

/** The heading of a day in a conversation: "Hoje", "Ontem", "terça, 17 de novembro". */
export function formatDayHeading(iso: string, now: Date): string {
  const at = valid(iso);
  if (!at) {
    return "";
  }
  const ago = daysAgo(at, now);
  if (ago === 0) {
    return "Hoje";
  }
  if (ago === 1) {
    return "Ontem";
  }
  const day = `${weekday(at)}, ${longDayFormat.format(at)}`;
  return sameYear(at, now) ? day : `${day} de ${dayKey(at).slice(0, 4)}`;
}

/**
 * A cost that arrives in millionths of a dollar. A reply costs a fraction of a cent, so the
 * decimals grow until two digits of the value show: US$ 0,0012 and not US$ 0,00.
 */
export function formatCost(microusd: number): string {
  const micro = Number.isFinite(microusd) && microusd > 0 ? Math.round(microusd) : 0;
  let decimals = 2;
  if (micro > 0 && micro < 1_000_000) {
    const leadingZeros = 6 - String(micro).length;
    decimals = Math.min(6, Math.max(2, leadingZeros + 2));
  }
  // Integer arithmetic, so that the rounding does not depend on a binary fraction.
  const unit = 10 ** decimals;
  const scaled = Math.round(micro / 10 ** (6 - decimals));
  const whole = wholeFormat.format(Math.floor(scaled / unit));
  const fraction = String(scaled % unit).padStart(decimals, "0");
  return `US$ ${whole},${fraction}`;
}

/** 3 ms, 2,3 s, 11 s, 1 min 05 s */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 1) {
    return "menos de 1 ms";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 9950) {
    return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
  }
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) {
    return `${seconds} s`;
  }
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

/** 1.548 */
export function formatCount(value: number): string {
  return wholeFormat.format(value);
}
