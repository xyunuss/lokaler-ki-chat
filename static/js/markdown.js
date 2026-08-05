/**
 * Markdown rendering for model output.
 *
 * Two rules, both learned the hard way in the previous version:
 *
 * 1. Model output is not trusted. Raw HTML tokens are dropped, so a model
 *    emitting <img onerror=...> - or repeating it out of an uploaded
 *    document - cannot execute anything.
 * 2. Highlighting happens once per code block, not once per token. The old
 *    code called hljs.highlightAll() on every streamed chunk, which walked
 *    the whole page each time.
 */

import { icon } from './icons.js';

const renderer = new marked.Renderer();
renderer.html = () => '';

marked.setOptions({
  renderer,
  breaks: true,
  gfm: true,
  langPrefix: 'hljs language-',
  highlight(code, lang) {
    const language = lang && hljs.getLanguage(lang) ? lang : null;
    try {
      return language
        ? hljs.highlight(code, { language }).value
        : hljs.highlightAuto(code).value;
    } catch {
      return code;
    }
  },
});

export function renderMarkdown(text) {
  return marked.parse(text ?? '');
}

/** Add a copy button to every code block that does not have one yet. */
export function enhanceCodeBlocks(container) {
  for (const pre of container.querySelectorAll('pre')) {
    if (pre.querySelector('.code-copy')) continue;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'code-copy';
    button.textContent = 'Copy';
    button.addEventListener('click', async () => {
      const code = pre.querySelector('code')?.textContent ?? '';
      try {
        await navigator.clipboard.writeText(code);
        button.textContent = 'Copied';
      } catch {
        button.textContent = 'Press Ctrl+C';
      }
      setTimeout(() => {
        button.textContent = 'Copy';
      }, 1500);
    });

    pre.appendChild(button);
  }
}

/** Small helper used for message action buttons. */
export function actionButton(label, iconName, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'message__action';
  const svg = icon(iconName, 13);
  if (svg) button.appendChild(svg);
  button.append(label);
  button.addEventListener('click', onClick);
  return button;
}
