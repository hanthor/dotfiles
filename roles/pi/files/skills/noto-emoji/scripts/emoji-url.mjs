#!/usr/bin/env node
// Converts emoji characters to their Noto animated GIF CDN URLs.
//
// Usage:  node emoji-url.mjs "🐟" "🧰"
// Output: {"🐟":"https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif",...}

const BASE = 'https://fonts.gstatic.com/s/e/notoemoji/latest';
const SIZE = 512;

function emojiToCodepoint(emoji) {
  const points = [];
  for (const cp of emoji) {
    points.push(cp.codePointAt(0).toString(16));
  }
  return points.join('_');
}

function emojiUrl(emoji, size = SIZE) {
  const cp = emojiToCodepoint(emoji);
  return `${BASE}/${cp}/${size}.gif`;
}

const emojis = process.argv.slice(2);
if (emojis.length === 0) {
  // Read from stdin for piping
  const chunks = [];
  process.stdin.on('data', c => chunks.push(c));
  process.stdin.on('end', () => {
    const input = Buffer.concat(chunks).toString().trim();
    const result = {};
    for (const emoji of [...input]) {
      if (emoji.trim()) result[emoji] = emojiUrl(emoji);
    }
    if (Object.keys(result).length === 1) {
      console.log(Object.values(result)[0]);
    } else {
      console.log(JSON.stringify(result, null, 2));
    }
  });
} else if (emojis.length === 1) {
  console.log(emojiUrl(emojis[0]));
} else {
  const result = {};
  for (const e of emojis) result[e] = emojiUrl(e);
  console.log(JSON.stringify(result, null, 2));
}
