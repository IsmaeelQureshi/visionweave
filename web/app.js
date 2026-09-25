// The browser is a client of the Python API; inference stays in the backend.
const $ = (id) => document.getElementById(id);
const terminal = new Set(['completed', 'failed', 'cancelled']);
const state = {job: null, jobs: [], preview: 0, offset: 0, total: 0,
  selection: 0, draw: 0, page: 0, timer: null, playing: null, uploading: false,
  videoSupported: false, maxUpload: 100 * 1024 * 1024};

function report(message = '') {
  $('error').textContent = message;
  $('error').hidden = !message;
}

async function request(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options,
    headers: {'X-VisionWeave-Request': '1', ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

function post(path, data = {}) {
  return request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
}

function sourceChanged() {
  const video = document.querySelector('input[name="source"]:checked').value === 'video';
  $('demo-input').hidden = video;
  $('video-input').hidden = !video;
  $('stride').disabled = !video;
  $('run-button').disabled = state.uploading || (video && !state.videoSupported);
  $('video-file').disabled = !state.videoSupported;
}

function stopPlayback() {
  clearInterval(state.playing);
  state.playing = null;
  $('play').textContent = '▶';
  $('play').setAttribute('aria-label', 'Play sampled frames');
}

function togglePlayback() {
  if (state.playing) return stopPlayback();
  const frames = state.job?.previews || [];
  if (frames.length < 2) return;
  $('play').textContent = 'Ⅱ';
  $('play').setAttribute('aria-label', 'Pause sampled frames');
  // This is a sampled-frame inspector, not timing-accurate source video playback.
  state.playing = setInterval(() => {
    state.preview = (state.preview + 1) % (state.job?.previews.length || 1);
    $('frame-slider').value = String(state.preview);
    drawFrame();
  }, 180);
}

function drawFrame() {
  const job = state.job;
  const frame = job?.previews[state.preview];
  const generation = ++state.draw;
  const canvas = $('frame-canvas');
  if (!frame) {
    canvas.hidden = true;
    $('viewer-empty').hidden = false;
    $('frame-caption').hidden = true;
    $('frame-counter').textContent = 'No frames yet';
    return;
  }
  const image = new Image();
  image.onload = () => {
    if (generation !== state.draw || state.job?.id !== job.id) return;
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0);
    const sx = canvas.width / frame.width;
    const sy = canvas.height / frame.height;
    context.lineWidth = Math.max(2, canvas.width / 300);
    for (const row of frame.rows) {
      if (row.kind === 'box' && $('show-boxes').checked) {
        context.strokeStyle = '#ffaaa0';
        context.strokeRect(row.x1 * sx, row.y1 * sy, (row.x2 - row.x1) * sx, (row.y2 - row.y1) * sy);
      } else if (row.kind === 'point' && $('show-points').checked) {
        const x = row.x1 * sx, y = row.y1 * sy;
        context.strokeStyle = '#a2ffe1';
        context.beginPath();
        context.arc(x, y, 9, 0, Math.PI * 2);
        context.moveTo(x - 15, y); context.lineTo(x + 15, y);
        context.moveTo(x, y - 15); context.lineTo(x, y + 15);
        context.stroke();
      }
    }
    canvas.hidden = false;
    $('viewer-empty').hidden = true;
    $('frame-caption').hidden = false;
    const time = frame.timestamp_sec == null ? 'Time unavailable' : `${frame.timestamp_sec.toFixed(2)} s`;
    const labels = frame.rows.filter(r => r.kind !== 'empty').map(r => r.label).join(', ') || 'No detections';
    canvas.setAttribute('aria-label', `Source frame ${frame.index}, ${time}. ${labels}.`);
    $('frame-caption').textContent = `FRAME ${String(frame.index).padStart(3, '0')} / ${time}`;
    $('frame-counter').textContent = `${state.preview + 1} / ${job.previews.length}`;
  };
  image.onerror = () => {if (generation === state.draw) report('Could not load this frame. Try refreshing the run.');};
  image.src = `/api/jobs/${job.id}/frames/${frame.index}.jpg`;
}

function renderJob(job) {
  const previousCount = state.job?.previews.length || 0;
  const previousStatus = state.job?.status;
  state.job = job;
  $('run-title').textContent = job.name;
  $('run-subtitle').textContent = job.kind === 'demo'
    ? 'Synthetic scene · 30 FPS · two independent adapters'
    : `Uploaded video · ${job.stride === 1 ? 'all frames' : `sampled every ${job.stride} frames`} · demo adapters`;
  $('status').textContent = job.status;
  $('status').className = `status ${job.status}`;
  for (const metric of ['frames', 'boxes', 'points', 'rows']) $('metric-' + metric).textContent = job[metric].toLocaleString();
  const active = !terminal.has(job.status);
  $('progress-panel').hidden = !active;
  $('progress-label').textContent = job.status === 'running'
    ? `${job.frames} of up to ${job.max_frames} frames · ${job.fps} frames/s`
    : job.status === 'queued' ? 'Queued · waiting for the processing worker' : job.status === 'cancelling' ? 'Stopping the run…' : 'Receiving video…';
  $('job-progress').max = job.max_frames;
  $('job-progress').value = job.frames;
  $('cancel').disabled = job.status === 'cancelling';
  $('frame-slider').max = Math.max(0, job.previews.length - 1);
  $('frame-slider').disabled = job.previews.length < 2;
  $('play').disabled = job.previews.length < 2;
  state.preview = Math.min(state.preview, Math.max(0, job.previews.length - 1));
  $('frame-slider').value = String(state.preview);
  $('preview-note').textContent = `${job.previews.length} sampled previews${job.status === 'completed' ? ` · processed in ${job.elapsed_sec.toFixed(2)} s` : ''}`;
  const complete = job.status === 'completed';
  $('download').classList.toggle('disabled', !complete);
  $('download').setAttribute('aria-disabled', String(!complete));
  $('download').tabIndex = complete ? 0 : -1;
  if (complete) $('download').href = `/api/jobs/${job.id}/csv`;
  else $('download').removeAttribute('href');
  if (!previousCount || previousStatus !== job.status) drawFrame();
  if (job.error) report(job.error);
}

function renderHistory() {
  const history = $('history');
  history.replaceChildren();
  if (!state.jobs.length) {
    const message = document.createElement('p');
    message.className = 'muted small'; message.textContent = 'Your completed runs will live here.';
    history.append(message); return;
  }
  for (const job of state.jobs.slice(0, 8)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `history-item${state.job?.id === job.id ? ' selected' : ''}`;
    button.setAttribute('aria-pressed', String(state.job?.id === job.id));
    const title = document.createElement('strong'); title.textContent = job.name;
    const detail = document.createElement('span');
    detail.textContent = `${job.status} · ${job.frames} frames · ${new Date(job.created_at * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`;
    button.append(title, detail);
    button.addEventListener('click', () => selectJob(job.id).catch(error => report(error.message)));
    history.append(button);
  }
}

async function loadHistory() {
  state.jobs = (await request('/api/jobs')).jobs;
  renderHistory();
}

function emptyResults(message) {
  $('results-body').replaceChildren();
  const row = document.createElement('tr'), cell = document.createElement('td');
  cell.colSpan = 6; cell.className = 'empty-table'; cell.textContent = message;
  row.append(cell); $('results-body').append(row);
  $('result-count').textContent = '0 results';
  $('next').disabled = $('previous').disabled = true;
}

async function loadResults() {
  const job = state.job;
  const selection = state.selection;
  const page = ++state.page;
  if (!job || job.status !== 'completed') {
    emptyResults(job?.status === 'failed' ? 'This run did not produce a CSV. See the error message.'
      : job?.status === 'cancelled' ? 'Run cancelled. Partial CSV results were discarded.'
        : 'Results will appear when your analysis is complete.');
    return;
  }
  $('previous').disabled = $('next').disabled = true;
  const data = await request(`/api/jobs/${job.id}/results?offset=${state.offset}&limit=20`);
  if (selection !== state.selection || page !== state.page) return;
  state.total = data.total;
  $('results-body').replaceChildren();
  for (const result of data.rows) {
    const row = document.createElement('tr');
    const values = [result.frame_index, result.timestamp_sec === '' ? '—' : `${Number(result.timestamp_sec).toFixed(2)} s`,
      result.adapter.replace('demo_', ''), result.kind, result.label || '—',
      result.x1 === '' ? '—' : `${Number(result.x1).toFixed(1)}, ${Number(result.y1).toFixed(1)}`];
    values.forEach((value, index) => {
      const cell = document.createElement('td');
      if (index === 3) {
        const badge = document.createElement('span'); badge.className = `kind-label kind-${result.kind}`; badge.textContent = value; cell.append(badge);
      } else cell.textContent = value;
      row.append(cell);
    });
    $('results-body').append(row);
  }
  $('result-count').textContent = `${data.offset + 1}–${data.offset + data.rows.length} of ${data.total} rows`;
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + 20 >= data.total;
}

async function selectJob(id) {
  const selection = ++state.selection;
  clearTimeout(state.timer); stopPlayback(); report();
  state.offset = 0; state.preview = 0; state.job = null;
  ++state.draw;
  const job = await request(`/api/jobs/${id}`);
  if (selection !== state.selection) return;
  renderJob(job); renderHistory(); await loadResults();
  if (!terminal.has(job.status)) poll(id, selection);
}

function poll(id, selection) {
  state.timer = setTimeout(async () => {
    try {
      const job = await request(`/api/jobs/${id}`);
      if (selection !== state.selection) return;
      renderJob(job);
      if (terminal.has(job.status)) {await loadResults(); await loadHistory();}
      else poll(id, selection);
    } catch (error) {
      if (selection !== state.selection) return;
      report(`Connection interrupted: ${error.message} Retrying…`);
      poll(id, selection);
    }
  }, 600);
}

function upload(file, maxFrames, stride) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = new URLSearchParams({name: file.name, max_frames: String(maxFrames), stride: String(stride)});
    xhr.open('POST', `/api/jobs/video?${query}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-VisionWeave-Request', '1');
    xhr.timeout = 120000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) $('upload-progress').value = event.loaded / event.total * 100;
    };
    xhr.onerror = () => reject(new Error('Upload failed. Check that the local server is running.'));
    xhr.ontimeout = () => reject(new Error('Upload timed out. Try a smaller video.'));
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) reject(new Error(data.error || 'Upload failed.'));
        else resolve(data);
      } catch {reject(new Error('The server returned an unexpected response.'));}
    };
    xhr.send(file);
  });
}

async function startRun(forceDemo = false) {
  if (state.uploading) return;
  report();
  const maxFrames = Number($('frame-limit').value);
  const stride = Number($('stride').value);
  if (!Number.isInteger(maxFrames) || maxFrames < 1 || maxFrames > 600) throw new Error('Choose a frame limit between 1 and 600.');
  if (!Number.isInteger(stride) || stride < 1 || stride > 30) throw new Error('Choose frame sampling between 1 and 30.');
  const video = !forceDemo && document.querySelector('input[name="source"]:checked').value === 'video';
  const file = $('video-file').files[0];
  if (video && !state.videoSupported) throw new Error('Install the optional video dependencies to process uploaded videos.');
  if (video && !file) throw new Error('Choose a video file first.');
  if (video && (file.size > state.maxUpload || file.size === 0)) throw new Error('Choose a nonempty video smaller than 100 MB.');
  state.uploading = true;
  $('run-button').disabled = $('quick-demo').disabled = true;
  $('run-button').firstElementChild.textContent = video ? 'Uploading…' : 'Starting…';
  $('upload-progress').hidden = !video; $('upload-progress').value = 0;
  try {
    const job = video ? await upload(file, maxFrames, stride) : await post('/api/jobs/demo', {max_frames: maxFrames});
    await loadHistory();
    await selectJob(job.id);
    return {id: job.id, status: state.job.status};
  } finally {
    state.uploading = false; sourceChanged();
    $('quick-demo').disabled = false;
    $('run-button').firstElementChild.textContent = 'Run analysis';
    $('upload-progress').hidden = true;
  }
}

document.querySelectorAll('input[name="source"]').forEach(input => input.addEventListener('change', sourceChanged));
$('run-form').addEventListener('submit', (event) => {event.preventDefault(); startRun().catch(error => report(error.message));});
$('quick-demo').addEventListener('click', () => startRun(true).catch(error => report(error.message)));
$('refresh').addEventListener('click', async () => {
  try {report(); await loadHistory(); if (state.job) await selectJob(state.job.id);}
  catch (error) {report(error.message);}
});
$('cancel').addEventListener('click', async () => {
  const id = state.job?.id;
  if (!id) return;
  $('cancel').disabled = true;
  try {const job = await post(`/api/jobs/${id}/cancel`); if (state.job?.id === id) renderJob(job);}
  catch (error) {report(error.message); $('cancel').disabled = false;}
});
$('frame-slider').addEventListener('input', () => {stopPlayback(); state.preview = Number($('frame-slider').value); drawFrame();});
$('play').addEventListener('click', togglePlayback);
for (const id of ['show-boxes', 'show-points']) $(id).addEventListener('change', drawFrame);
for (const [id, delta] of [['previous', -20], ['next', 20]]) $(id).addEventListener('click', () => {
  state.offset = Math.max(0, state.offset + delta); loadResults().catch(error => report(error.message));
});

async function initialize() {
  try {
    const health = await request('/api/health');
    state.videoSupported = health.video_supported; state.maxUpload = health.max_upload_bytes;
    $('video-support').textContent = health.video_supported ? 'Video decoding is available.' : 'Video upload is unavailable until you install requirements-video.txt. The synthetic demo is ready.';
    sourceChanged();
    await loadHistory();
    if (state.jobs.length) await selectJob(state.jobs[0].id);
  } catch (error) {report(`Could not reach the backend. ${error.message}`);}
}
initialize();

// Optional browser-agent integration. Uses the same actions as the visible UI.
// Unsupported browsers simply retain the normal interface.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  const register = (tool) => {
    try {
      Promise.resolve(document.modelContext.registerTool(tool, {signal: lifecycle.signal}))
        .catch(() => {}); // Optional integration failure must not disable the app.
    } catch { /* Browser may expose an incomplete experimental API. */ }
  };
  register({name: 'start_demo_analysis', title: 'Start synthetic video analysis',
    description: 'Create a new backend analysis job using synthetic frames and select it in the workspace.',
    inputSchema: {type: 'object', properties: {max_frames: {type: 'integer', minimum: 1, maximum: 600}}, required: ['max_frames'], additionalProperties: false},
    annotations: {readOnlyHint: false, untrustedContentHint: false},
    async execute(input) {
      if (!input || Object.keys(input).some(key => key !== 'max_frames') || !Number.isInteger(input.max_frames) || input.max_frames < 1 || input.max_frames > 600) throw new Error('max_frames must be an integer from 1 to 600.');
      if (state.uploading) throw new Error('Another input is being submitted.');
      document.querySelector('input[name="source"][value="demo"]').checked = true;
      $('frame-limit').value = String(input.max_frames);
      sourceChanged();
      return startRun(true);
    }});
  register({name: 'get_selected_analysis_status', title: 'Read selected analysis status',
    description: 'Read current backend status and result counts for the selected run.',
    inputSchema: {type: 'object', properties: {}, additionalProperties: false},
    annotations: {readOnlyHint: true, untrustedContentHint: false},
    async execute(input) {
      if (!input || Object.keys(input).length) throw new Error('This tool takes an empty object.');
      if (!state.job) return {selected: false};
      const job = await request(`/api/jobs/${state.job.id}`);
      return {id: job.id, status: job.status, frames: job.frames, rows: job.rows, error: job.error};
    }});
  window.addEventListener('pagehide', () => lifecycle.abort(), {once: true});
}
