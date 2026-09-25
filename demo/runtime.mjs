import {generateFrame, WIDTH, HEIGHT, toCSV} from './engine.mjs';
const jobs = new Map();
const workers = new Map();
const urls = new Map();
const snapshot = job => structuredClone(Object.fromEntries(Object.entries(job).filter(([key]) => key !== 'results')));

// In-memory transport for the shared workspace UI. No HTTP API or shared history.
export async function request(path, options = {}) {
  if (path === '/api/jobs/demo' && options.method === 'POST') {
    const {max_frames} = JSON.parse(options.body);
    if (!Number.isInteger(max_frames) || max_frames < 1 || max_frames > 600) throw new Error('Choose 1–600 frames.');
    if (workers.size) throw new Error('Wait for the current analysis to finish, or cancel it.');
    if (!globalThis.Worker) throw new Error('This browser does not support background analysis. Try a current desktop browser.');
    const id = crypto.randomUUID();
    const worker = new Worker(new URL('./worker.mjs', import.meta.url), {type:'module'});
    const job = {id,name:'Synthetic shapes',kind:'demo',status:'running',created_at:Date.now()/1000,max_frames,
      frames:0,rows:0,boxes:0,points:0,empty:0,elapsed_sec:0,fps:0,previews:[],error:null};
    // Retain only eight runs, with bounded preview metadata and no stored images.
    if (jobs.size >= 8) {
      const oldest = jobs.keys().next().value;
      jobs.delete(oldest); if (urls.has(oldest)) URL.revokeObjectURL(urls.get(oldest)); urls.delete(oldest);
    }
    jobs.set(id,job); workers.set(id,worker);
    worker.onmessage = ({data}) => {
      Object.assign(job,data);
      if (['completed','failed'].includes(job.status)) {worker.terminate(); workers.delete(id);}
    };
    worker.onerror = event => {
      event.preventDefault(); Object.assign(job,{status:'failed',error:'The analysis worker could not run. Reload the page and try again.'});
      worker.terminate(); workers.delete(id);
    };
    worker.postMessage({maxFrames:max_frames});
    return snapshot(job);
  }
  if (path === '/api/jobs') return {jobs:[...jobs.values()].reverse().map(snapshot)};
  const url = new URL(path,'https://demo.invalid');
  const [, , , id, action] = url.pathname.split('/');
  const job = jobs.get(id);
  if (!job) throw new Error('This run is no longer in this session. Start a new analysis.');
  if (action === 'cancel') {
    if (workers.has(id)) {workers.get(id).terminate(); workers.delete(id); job.status='cancelled'; delete job.results;}
  } else if (action === 'results') {
    if (job.status !== 'completed') throw new Error('This run has not completed.');
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 20);
    return {rows:job.results.slice(offset,offset+limit),total:job.rows,offset,limit};
  }
  return snapshot(job);
}

export function frameSource(index) {
  const canvas = document.createElement('canvas'); canvas.width=WIDTH; canvas.height=HEIGHT;
  canvas.getContext('2d').putImageData(new ImageData(generateFrame(index),WIDTH,HEIGHT),0,0);
  return canvas.toDataURL('image/png');
}
export function csvURL(id) {
  if (!urls.has(id)) urls.set(id,URL.createObjectURL(new Blob([toCSV(jobs.get(id).results)],{type:'text/csv;charset=utf-8'})));
  return urls.get(id);
}
window.addEventListener('pagehide',()=>{for (const worker of workers.values()) worker.terminate();});
