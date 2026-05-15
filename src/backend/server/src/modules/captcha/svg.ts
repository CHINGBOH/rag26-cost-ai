/**
 * 自建 SVG 图形验证码（无外部依赖，做第一道闸）
 * Issue #156
 */
import * as crypto from 'crypto';

const CHARSET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

export function generateSvgCaptcha(length = 5): { id: string; svg: string; answer: string } {
  const answer = Array.from({ length }, () => CHARSET[crypto.randomInt(CHARSET.length)]).join('');
  const id = crypto.randomUUID();

  const width = 140;
  const height = 50;
  const noise = Array.from({ length: 6 }, () => {
    const x1 = crypto.randomInt(width);
    const y1 = crypto.randomInt(height);
    const x2 = crypto.randomInt(width);
    const y2 = crypto.randomInt(height);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="hsl(${crypto.randomInt(360)},60%,70%)" stroke-width="1.2"/>`;
  }).join('');

  const chars = answer
    .split('')
    .map((ch, i) => {
      const x = 18 + i * 24 + crypto.randomInt(6);
      const y = 32 + crypto.randomInt(8);
      const rot = crypto.randomInt(40) - 20;
      const hue = crypto.randomInt(360);
      return `<text x="${x}" y="${y}" font-family="Verdana,monospace" font-size="28" font-weight="bold" fill="hsl(${hue},70%,40%)" transform="rotate(${rot} ${x} ${y})">${ch}</text>`;
    })
    .join('');

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#f7f9fc"/>${noise}${chars}</svg>`;

  return { id, svg, answer };
}

export function hashAnswer(answer: string): string {
  return crypto.createHash('sha256').update(answer.toUpperCase()).digest('hex');
}
