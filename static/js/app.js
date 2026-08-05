/**
 * Local AI Chat - application logic.
 *
 * Deliberately framework-free: the project's promise is "clone it and run it",
 * and adding a build step would break that. The code is split into modules
 * instead (api / markdown / icons), which is where the previous 500-line
 * single-file version fell apart.
 */

import { ApiError, api } from './api.js';
import { actionButton, enhanceCodeBlocks, renderMarkdown } from './markdown.js';
import { applyIcons, icon } from './icons.js';

/* ------------------------------------------------------------------ refs */

const $ = (id) => document.getElementById(id);

const el = {
  layout: $('layout'),
  sidebar: $('sidebar'),
  openSidebar: $('openSidebar'),
  closeSidebar: $('closeSidebar'),
  newChat: $('newChat'),
  search: $('search'),
  conversationList: $('conversationList'),
  themeToggle: $('themeToggle'),
  openModels: $('openModels'),
  modelSelect: $('modelSelect'),
  contextInfo: $('contextInfo'),
  openSettings: $('openSettings'),
  exportChat: $('exportChat'),
  banner: $('banner'),
  messages: $('messages'),
  attachments: $('attachments'),
  fileInput: $('fileInput'),
  attachBtn: $('attachBtn'),
  prompt: $('prompt'),
  sendBtn: $('sendBtn'),
  stopBtn: $('stopBtn'),
  dropzone: $('dropzone'),
  toast: $('toast'),
  settingsDialog: $('settingsDialog'),
  systemPrompt: $('systemPrompt'),
  temperature: $('temperature'),
  temperatureOut: $('temperatureOut'),
  topP: $('topP'),
  topPOut: $('topPOut'),
  numCtx: $('numCtx'),
  saveSettings: $('saveSettings'),
  modelsDialog: $('modelsDialog'),
  modelList: $('modelList'),
  pullName: $('pullName'),
  pullBtn: $('pullBtn'),
  pullProgress: $('pullProgress'),
  pullFill: $('pullFill'),
  pullLabel: $('pullLabel'),
  closeModels: $('closeModels'),
};

/* ----------------------------------------------------------------- state */

const state = {
  conversations: [],
  conversationId: null,
  messages: [],
  models: [],
  model: localStorage.getItem('model') || '',
  attachments: [],
  settings: { systemPrompt: '', temperature: 0.7, topP: 0.9, numCtx: null },
  generating: false,
  controller: null,
};

const SUGGESTIONS = [
  { title: 'Explain a concept', text: 'Explain how HTTP streaming works, with a small example.' },
  { title: 'Review some code', text: 'Review this function for edge cases and readability:\n\n' },
  { title: 'Summarise a document', text: 'Summarise the attached document in five bullet points.' },
  { title: 'Draft something', text: 'Draft a short, friendly email declining a meeting invitation.' },
];

/* --------------------------------------------------------------- helpers */

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    el.toast.hidden = true;
  }, 2400);
}

function showBanner(message, hint) {
  el.banner.replaceChildren();
  const warn = icon('warning', 16);
  if (warn) el.banner.appendChild(warn);

  const text = document.createElement('span');
  text.textContent = hint ? `${message} ${hint}` : message;
  el.banner.appendChild(text);
  el.banner.hidden = false;
}

function hideBanner() {
  el.banner.hidden = true;
}

function formatBytes(bytes) {
  if (!bytes) return '';
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value);
}

function scrollToBottom(force = false) {
  const { scrollTop, scrollHeight, clientHeight } = el.messages;
  // Don't yank the view away while the user is reading further up.
  if (force || scrollHeight - scrollTop - clientHeight < 140) {
    el.messages.scrollTop = el.messages.scrollHeight;
  }
}

/* ----------------------------------------------------------------- theme */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('theme', theme);
}

function initTheme() {
  const stored = localStorage.getItem('theme');
  const preferred = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  applyTheme(stored || preferred);

  el.themeToggle.addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
}

/* ---------------------------------------------------------------- models */

async function loadModels() {
  try {
    const { models } = await api.models();
    state.models = models;
    hideBanner();
  } catch (error) {
    state.models = [];
    showBanner(error.message, error.hint);
  }

  el.modelSelect.replaceChildren();

  if (!state.models.length) {
    const option = document.createElement('option');
    option.textContent = 'No models installed';
    option.value = '';
    el.modelSelect.appendChild(option);
    el.modelSelect.disabled = true;
    return;
  }

  el.modelSelect.disabled = false;
  for (const model of state.models) {
    const option = document.createElement('option');
    option.value = model.name;
    option.textContent = model.parameterSize
      ? `${model.name} · ${model.parameterSize}`
      : model.name;
    el.modelSelect.appendChild(option);
  }

  if (!state.models.some((m) => m.name === state.model)) {
    state.model = state.models[0].name;
  }
  el.modelSelect.value = state.model;
  localStorage.setItem('model', state.model);
}

async function checkHealth() {
  try {
    const health = await api.health();
    if (health.ollama?.reachable) hideBanner();
  } catch (error) {
    showBanner(error.message, error.hint);
  }
}

/* --------------------------------------------------------- conversations */

async function loadConversations(query = '') {
  try {
    const { conversations } = await api.conversations(query);
    state.conversations = conversations;
    renderConversations();
  } catch {
    /* the banner already covers a dead backend */
  }
}

function renderConversations() {
  el.conversationList.replaceChildren();

  if (!state.conversations.length) {
    const empty = document.createElement('p');
    empty.className = 'sidebar__empty';
    empty.textContent = el.search.value ? 'Nothing found.' : 'No conversations yet.';
    el.conversationList.appendChild(empty);
    return;
  }

  for (const conversation of state.conversations) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'conversation';
    item.classList.toggle('is-active', conversation.id === state.conversationId);

    const text = document.createElement('span');
    text.className = 'conversation__text';

    const title = document.createElement('span');
    title.className = 'conversation__title';
    title.textContent = conversation.title;

    const meta = document.createElement('span');
    meta.className = 'conversation__meta';
    meta.textContent = [
      conversation.model,
      `${conversation.messageCount} message${conversation.messageCount === 1 ? '' : 's'}`,
    ]
      .filter(Boolean)
      .join(' · ');

    text.append(title, meta);
    item.appendChild(text);

    const remove = document.createElement('span');
    remove.className = 'conversation__delete';
    remove.setAttribute('role', 'button');
    remove.setAttribute('tabindex', '0');
    remove.setAttribute('aria-label', `Delete ${conversation.title}`);
    const trash = icon('trash', 14);
    if (trash) remove.appendChild(trash);

    const doDelete = async (event) => {
      event.stopPropagation();
      if (!confirm(`Delete "${conversation.title}"?`)) return;
      await api.deleteConversation(conversation.id);
      if (state.conversationId === conversation.id) startNewChat();
      loadConversations(el.search.value.trim());
    };
    remove.addEventListener('click', doDelete);
    remove.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') doDelete(event);
    });

    item.appendChild(remove);
    item.addEventListener('click', () => openConversation(conversation.id));
    el.conversationList.appendChild(item);
  }
}

async function openConversation(id) {
  const conversation = await api.conversation(id);
  state.conversationId = id;
  state.messages = conversation.messages;
  state.settings.systemPrompt = conversation.systemPrompt || '';

  if (conversation.model && state.models.some((m) => m.name === conversation.model)) {
    state.model = conversation.model;
    el.modelSelect.value = conversation.model;
  }

  renderMessages();
  renderConversations();
  closeSidebarOnMobile();
  el.prompt.focus();
}

function startNewChat() {
  state.conversationId = null;
  state.messages = [];
  state.settings.systemPrompt = '';
  clearAttachments();
  renderMessages();
  renderConversations();
  el.prompt.focus();
}

async function ensureConversation() {
  if (state.conversationId) return state.conversationId;
  const conversation = await api.createConversation({
    model: state.model,
    systemPrompt: state.settings.systemPrompt || null,
  });
  state.conversationId = conversation.id;
  return conversation.id;
}

/* -------------------------------------------------------------- messages */

function renderMessages() {
  el.messages.replaceChildren();

  if (!state.messages.length) {
    el.messages.appendChild(buildEmptyState());
    updateContextInfo();
    return;
  }

  state.messages.forEach((message, index) => {
    el.messages.appendChild(
      buildMessage(message, index === state.messages.length - 1)
    );
  });

  updateContextInfo();
  scrollToBottom(true);
}

function buildEmptyState() {
  const wrapper = document.createElement('div');
  wrapper.className = 'empty';

  const heading = document.createElement('h1');
  heading.textContent = 'What can I help with?';

  const sub = document.createElement('p');
  sub.textContent = state.models.length
    ? 'Everything runs on this machine. Nothing leaves it.'
    : 'No model installed yet - open “Models” to download one.';

  const grid = document.createElement('div');
  grid.className = 'suggestions';

  for (const suggestion of SUGGESTIONS) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'suggestion';

    const strong = document.createElement('strong');
    strong.textContent = suggestion.title;
    button.append(strong, suggestion.text.split('\n')[0]);

    button.addEventListener('click', () => {
      el.prompt.value = suggestion.text;
      el.prompt.focus();
      autoResize();
    });
    grid.appendChild(button);
  }

  wrapper.append(heading, sub, grid);
  return wrapper;
}

function buildMessage(message, isLast) {
  const wrapper = document.createElement('article');
  wrapper.className = `message message--${message.role}`;
  wrapper.dataset.messageId = message.id ?? '';

  if (message.role === 'assistant') {
    const role = document.createElement('div');
    role.className = 'message__role';
    const dot = document.createElement('span');
    dot.className = 'message__dot';
    role.append(dot, 'Assistant');
    wrapper.appendChild(role);
  }

  const body = document.createElement('div');
  body.className = 'message__body';

  if (message.attachments?.length) {
    const list = document.createElement('div');
    list.className = 'message__attachments';
    for (const attachment of message.attachments) {
      list.appendChild(buildChip(attachment));
    }
    wrapper.appendChild(list);
  }

  if (message.role === 'user') {
    // User text is inserted as text, never as markup.
    body.textContent = stripAttachmentSections(message.content);
  } else {
    body.innerHTML = renderMarkdown(message.content);
    enhanceCodeBlocks(body);
  }

  wrapper.appendChild(body);
  wrapper.appendChild(buildMeta(message, body, isLast));
  return wrapper;
}

/** Hide the appended document text - the chips above already show it. */
function stripAttachmentSections(content) {
  const marker = content.indexOf('\n\n--- file: ');
  return marker === -1 ? content : content.slice(0, marker).trim();
}

function buildMeta(message, body, isLast) {
  const meta = document.createElement('div');
  meta.className = 'message__meta';

  if (message.stats) {
    const stats = document.createElement('span');
    const parts = [];
    if (message.stats.tokensPerSecond) parts.push(`${message.stats.tokensPerSecond} tok/s`);
    if (message.stats.completionTokens) {
      parts.push(`${formatNumber(message.stats.completionTokens)} tokens`);
    }
    if (message.stats.totalMs) parts.push(`${(message.stats.totalMs / 1000).toFixed(1)}s`);
    if (message.stats.cancelled) parts.push('stopped');
    stats.textContent = parts.join(' · ');
    if (parts.length) {
      meta.appendChild(stats);
      meta.classList.add('is-visible');
    }
  }

  meta.appendChild(
    actionButton('Copy', 'copy', async () => {
      await navigator.clipboard.writeText(message.content);
      toast('Copied');
    })
  );

  if (message.role === 'assistant' && isLast) {
    meta.appendChild(actionButton('Regenerate', 'refresh', regenerate));
  }

  if (message.role === 'user') {
    meta.appendChild(
      actionButton('Edit', 'edit', () => startEditing(message, body))
    );
  }

  return meta;
}

function startEditing(message, body) {
  const original = stripAttachmentSections(message.content);

  const textarea = document.createElement('textarea');
  textarea.value = original;
  textarea.rows = Math.min(12, original.split('\n').length + 1);
  textarea.style.width = '100%';

  const actions = document.createElement('div');
  actions.className = 'dialog__actions';

  const cancel = document.createElement('button');
  cancel.className = 'btn btn--ghost btn--small';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', renderMessages);

  const save = document.createElement('button');
  save.className = 'btn btn--primary btn--small';
  save.textContent = 'Save & resend';
  save.addEventListener('click', async () => {
    const text = textarea.value.trim();
    if (!text) return;
    // Editing rewrites history from that point on, like every chat app.
    await api.deleteFromMessage(state.conversationId, message.id);
    state.messages = state.messages.filter((m) => m.id < message.id);
    renderMessages();
    await send(text);
  });

  actions.append(cancel, save);
  body.replaceChildren(textarea, actions);
  textarea.focus();
}

function updateContextInfo() {
  const total = state.messages.reduce((sum, m) => sum + m.content.length, 0);
  if (!total) {
    el.contextInfo.hidden = true;
    return;
  }
  // Rough but honest: ~4 characters per token for European languages.
  el.contextInfo.textContent = `~${formatNumber(Math.round(total / 4))} tokens in context`;
  el.contextInfo.hidden = false;
}

/* ----------------------------------------------------------- attachments */

function buildChip(attachment, onRemove) {
  const chip = document.createElement('span');
  chip.className = `chip${attachment.error ? ' chip--error' : ''}`;

  const svg = icon(attachment.error ? 'warning' : 'file', 13);
  if (svg) chip.appendChild(svg);

  const name = document.createElement('strong');
  name.textContent = attachment.name;
  chip.appendChild(name);

  const detail = document.createElement('span');
  if (attachment.error) {
    detail.textContent = attachment.error;
  } else {
    const bits = [];
    if (attachment.pages) bits.push(`${attachment.pages}p`);
    if (attachment.chars) bits.push(`${formatNumber(attachment.chars)} chars`);
    if (attachment.truncated) bits.push('truncated');
    detail.textContent = bits.join(' · ');
  }
  chip.appendChild(detail);

  if (onRemove) {
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.setAttribute('aria-label', `Remove ${attachment.name}`);
    const close = icon('close', 12);
    if (close) remove.appendChild(close);
    remove.addEventListener('click', onRemove);
    chip.appendChild(remove);
  }

  return chip;
}

function renderAttachments() {
  el.attachments.replaceChildren();
  state.attachments.forEach((attachment, index) => {
    el.attachments.appendChild(
      buildChip(attachment, () => {
        state.attachments.splice(index, 1);
        renderAttachments();
      })
    );
  });
}

function clearAttachments() {
  state.attachments = [];
  renderAttachments();
}

async function handleFiles(files) {
  const list = [...files];
  if (!list.length) return;

  toast(`Reading ${list.length} file${list.length === 1 ? '' : 's'}…`);
  try {
    const { documents, errors } = await api.uploadDocuments(list);
    state.attachments.push(...documents);
    renderAttachments();

    for (const failure of errors ?? []) toast(failure.error);
  } catch (error) {
    toast(error.message);
  }
}

/* ----------------------------------------------------------- the streaming */

function setGenerating(active) {
  state.generating = active;
  el.sendBtn.hidden = active;
  el.stopBtn.hidden = !active;
  el.prompt.disabled = false; // typing the next message while it runs is fine
}

async function send(textOverride) {
  if (state.generating) return;

  const text = (textOverride ?? el.prompt.value).trim();
  if (!text && !state.attachments.length) return;

  if (!state.model) {
    toast('Install a model first.');
    return;
  }

  const attachments = [...state.attachments];

  if (!textOverride) {
    el.prompt.value = '';
    autoResize();
  }
  clearAttachments();

  // Optimistic: show the user turn immediately.
  state.messages.push({
    id: Number.MAX_SAFE_INTEGER,
    role: 'user',
    content: text,
    attachments: attachments.map(({ name, kind, chars, pages, truncated }) => ({
      name,
      kind,
      chars,
      pages,
      truncated,
    })),
  });
  renderMessages();

  await run({
    conversationId: await ensureConversation(),
    model: state.model,
    content: text,
    attachments,
    options: generationOptions(),
  });
}

async function regenerate() {
  if (state.generating || !state.conversationId) return;

  const last = state.messages[state.messages.length - 1];
  if (last?.role === 'assistant') state.messages.pop();
  renderMessages();

  await run({
    conversationId: state.conversationId,
    model: state.model,
    regenerate: true,
    options: generationOptions(),
  });
}

function generationOptions() {
  const options = {
    temperature: Number(el.temperature.value),
    top_p: Number(el.topP.value),
  };
  const ctx = Number(el.numCtx.value);
  if (ctx) options.num_ctx = ctx;
  return options;
}

async function run(payload) {
  setGenerating(true);
  state.controller = new AbortController();

  const message = { id: null, role: 'assistant', content: '', stats: null };
  state.messages.push(message);

  const element = buildMessage(message, true);
  const body = element.querySelector('.message__body');
  const cursor = document.createElement('span');
  cursor.className = 'cursor';
  body.appendChild(cursor);
  el.messages.appendChild(element);
  scrollToBottom(true);

  let lastPaint = 0;
  const paint = (force = false) => {
    const now = performance.now();
    // Re-parsing markdown per token is wasteful; ~20 fps looks identical.
    if (!force && now - lastPaint < 50) return;
    lastPaint = now;
    body.innerHTML = renderMarkdown(message.content);
    body.appendChild(cursor);
    scrollToBottom();
  };

  try {
    for await (const event of api.chat(payload, { signal: state.controller.signal })) {
      if (event.type === 'start') {
        if (event.title) loadConversations(el.search.value.trim());
        if (event.userMessageId) {
          const pending = state.messages.find((m) => m.id === Number.MAX_SAFE_INTEGER);
          if (pending) pending.id = event.userMessageId;
        }
      } else if (event.type === 'token') {
        message.content += event.content;
        paint();
      } else if (event.type === 'done') {
        message.id = event.messageId ?? null;
        message.stats = event.stats;
      } else if (event.type === 'error') {
        showBanner(event.error, event.hint);
        toast(event.error);
      }
    }
  } catch (error) {
    if (error.name !== 'AbortError') {
      const apiError = error instanceof ApiError ? error : null;
      showBanner(apiError?.message ?? 'Generation failed.', apiError?.hint);
      toast(apiError?.message ?? 'Generation failed.');
    }
  } finally {
    cursor.remove();
    setGenerating(false);
    state.controller = null;

    if (!message.content) {
      state.messages.pop();
    }
    renderMessages();
    loadConversations(el.search.value.trim());
  }
}

function stop() {
  state.controller?.abort();
  toast('Stopped');
}

/* --------------------------------------------------------------- dialogs */

function openSettings() {
  el.systemPrompt.value = state.settings.systemPrompt || '';
  el.settingsDialog.showModal();
}

async function saveSettings(event) {
  event.preventDefault();
  state.settings.systemPrompt = el.systemPrompt.value.trim();

  if (state.conversationId) {
    await api.updateConversation(state.conversationId, {
      systemPrompt: state.settings.systemPrompt || null,
    });
  }

  localStorage.setItem('temperature', el.temperature.value);
  localStorage.setItem('topP', el.topP.value);
  localStorage.setItem('numCtx', el.numCtx.value);

  el.settingsDialog.close();
  toast('Parameters saved');
}

async function openModels() {
  el.modelsDialog.showModal();
  el.modelList.replaceChildren();

  const loading = document.createElement('li');
  loading.textContent = 'Loading…';
  el.modelList.appendChild(loading);

  try {
    const { models } = await api.models();
    el.modelList.replaceChildren();

    if (!models.length) {
      const empty = document.createElement('li');
      empty.textContent = 'No models installed yet.';
      el.modelList.appendChild(empty);
    }

    for (const model of models) {
      const item = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = model.name;

      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = [model.parameterSize, model.quantization, formatBytes(model.sizeBytes)]
        .filter(Boolean)
        .join(' · ');

      item.append(name, meta);
      el.modelList.appendChild(item);
    }
  } catch (error) {
    el.modelList.replaceChildren();
    const failed = document.createElement('li');
    failed.textContent = error.message;
    el.modelList.appendChild(failed);
  }
}

async function pullModel() {
  const name = el.pullName.value.trim();
  if (!name) return;

  el.pullBtn.disabled = true;
  el.pullProgress.hidden = false;
  el.pullFill.style.width = '0%';
  el.pullLabel.textContent = 'starting…';

  try {
    for await (const event of api.pullModel(name)) {
      if (event.type === 'error') {
        toast(event.error);
        break;
      }
      if (event.type === 'progress') {
        el.pullFill.style.width = `${event.percent || 0}%`;
        el.pullLabel.textContent = event.total
          ? `${event.status} · ${event.percent}%`
          : event.status;
      }
      if (event.type === 'done') {
        el.pullFill.style.width = '100%';
        el.pullLabel.textContent = 'done';
        toast(`${name} is ready`);
        await loadModels();
        await openModels();
      }
    }
  } catch (error) {
    toast(error.message);
  } finally {
    el.pullBtn.disabled = false;
    el.pullName.value = '';
    setTimeout(() => {
      el.pullProgress.hidden = true;
    }, 1200);
  }
}

/* ----------------------------------------------------------------- input */

function autoResize() {
  el.prompt.style.height = 'auto';
  el.prompt.style.height = `${Math.min(el.prompt.scrollHeight, 220)}px`;
}

function closeSidebarOnMobile() {
  if (window.matchMedia('(max-width: 860px)').matches) {
    el.layout.classList.remove('is-open');
  }
}

function toggleSidebar(open) {
  if (window.matchMedia('(max-width: 860px)').matches) {
    el.layout.classList.toggle('is-open', open);
    return;
  }
  el.layout.classList.toggle('is-collapsed', !open);
  localStorage.setItem('sidebarCollapsed', String(!open));
}

function initShortcuts() {
  document.addEventListener('keydown', (event) => {
    const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);

    if (event.key === '/' && !typing) {
      event.preventDefault();
      toggleSidebar(true);
      el.search.focus();
    }

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      toggleSidebar(true);
      el.search.focus();
    }

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
      event.preventDefault();
      startNewChat();
    }

    if (event.key === 'Escape' && state.generating) {
      stop();
    }
  });
}

function initDragAndDrop() {
  let depth = 0;

  window.addEventListener('dragenter', (event) => {
    if (![...event.dataTransfer.types].includes('Files')) return;
    depth += 1;
    el.dropzone.hidden = false;
  });

  window.addEventListener('dragover', (event) => event.preventDefault());

  window.addEventListener('dragleave', () => {
    depth = Math.max(0, depth - 1);
    if (!depth) el.dropzone.hidden = true;
  });

  window.addEventListener('drop', (event) => {
    event.preventDefault();
    depth = 0;
    el.dropzone.hidden = true;
    if (event.dataTransfer.files.length) handleFiles(event.dataTransfer.files);
  });

  el.prompt.addEventListener('paste', (event) => {
    const files = [...(event.clipboardData?.files ?? [])];
    if (files.length) {
      event.preventDefault();
      handleFiles(files);
    }
  });
}

/* ------------------------------------------------------------------ init */

function wire() {
  el.newChat.addEventListener('click', startNewChat);
  el.openSidebar.addEventListener('click', () => toggleSidebar(true));
  el.closeSidebar.addEventListener('click', () => toggleSidebar(false));

  let searchTimer;
  el.search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadConversations(el.search.value.trim()), 180);
  });

  el.modelSelect.addEventListener('change', () => {
    state.model = el.modelSelect.value;
    localStorage.setItem('model', state.model);
    if (state.conversationId) {
      api.updateConversation(state.conversationId, { model: state.model }).catch(() => {});
    }
  });

  el.sendBtn.addEventListener('click', () => send());
  el.stopBtn.addEventListener('click', stop);

  el.prompt.addEventListener('input', autoResize);
  el.prompt.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  el.attachBtn.addEventListener('click', () => el.fileInput.click());
  el.fileInput.addEventListener('change', () => {
    handleFiles(el.fileInput.files);
    el.fileInput.value = '';
  });

  el.openSettings.addEventListener('click', openSettings);
  el.saveSettings.addEventListener('click', saveSettings);
  el.temperature.addEventListener('input', () => {
    el.temperatureOut.value = el.temperature.value;
  });
  el.topP.addEventListener('input', () => {
    el.topPOut.value = el.topP.value;
  });

  el.openModels.addEventListener('click', openModels);
  el.closeModels.addEventListener('click', () => el.modelsDialog.close());
  el.pullBtn.addEventListener('click', pullModel);
  el.pullName.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') pullModel();
  });

  el.exportChat.addEventListener('click', () => {
    if (!state.conversationId) {
      toast('Nothing to export yet.');
      return;
    }
    window.location.href = api.exportUrl(state.conversationId);
  });
}

async function init() {
  applyIcons();
  initTheme();
  wire();
  initShortcuts();
  initDragAndDrop();

  el.temperature.value = localStorage.getItem('temperature') ?? '0.7';
  el.topP.value = localStorage.getItem('topP') ?? '0.9';
  el.numCtx.value = localStorage.getItem('numCtx') ?? '';
  el.temperatureOut.value = el.temperature.value;
  el.topPOut.value = el.topP.value;

  if (localStorage.getItem('sidebarCollapsed') === 'true') {
    el.layout.classList.add('is-collapsed');
  }

  await loadModels();
  await loadConversations();
  renderMessages();

  await checkHealth();
  setInterval(checkHealth, 30000);

  el.prompt.focus();
}

init();
