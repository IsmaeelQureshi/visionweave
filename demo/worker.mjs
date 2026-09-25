import { generateFrame, analyzeFrame, WIDTH, HEIGHT } from './engine.mjs';
self.onmessage = ({data:{maxFrames}}) => {
  try {
    const rows = [], previews = [], start = performance.now();
    let boxes = 0, points = 0, empty = 0;
    const interval = Math.max(1, Math.ceil(maxFrames / 120));
    for (let index = 0; index < maxFrames; index++) {
      const results = analyzeFrame(generateFrame(index), index);
      rows.push(...results);
      for (const row of results) {
        if (row.kind === 'box') boxes++;
        else if (row.kind === 'point') points++;
        else empty++;
      }
      if (index % interval === 0) previews.push({index,timestamp_sec:index/30,width:WIDTH,height:HEIGHT,rows:results});
      if (index === 0 || (index+1) % 5 === 0 || index+1 === maxFrames) {
        const elapsed_sec = (performance.now()-start)/1000;
        self.postMessage({status:index+1 === maxFrames ? 'completed' : 'running',frames:index+1,
          rows:rows.length,boxes,points,empty,previews,elapsed_sec,fps:Math.round((index+1)/Math.max(elapsed_sec,.001)),
          ...(index+1 === maxFrames ? {results:rows} : {})});
      }
    }
  } catch { self.postMessage({status:'failed',error:'Analysis failed. Please start a new run.'}); }
};
