// Browser-native synthetic scene and independent pixel detectors.
// Unlike the Python adapters, these inspect source-resolution pixels directly.
export const WIDTH = 640, HEIGHT = 360;
export const FIELDS = ['frame_index','timestamp_sec','frame_width','frame_height','adapter',
  'prediction_index','kind','label','confidence','visible','x1','y1','x2','y2',
  'x1_norm','y1_norm','x2_norm','y2_norm'];

export function generateFrame(index) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  const left = 35 + (index * 3) % 400;
  const cx = 320 + Math.round(160 * Math.sin(index / 16));
  for (let y = 0; y < HEIGHT; y++) for (let x = 0; x < WIDTH; x++) {
    const p = (y * WIDTH + x) * 4;
    let color = [20, 27, 40];
    if (index % 60 < 50 && x >= left && x <= left + 85 && y >= 80 && y <= 145) color = [235, 65, 65];
    if (index % 60 < 40 && (x-cx)**2 + (y-270)**2 <= 144) color = [65,225,85];
    pixels[p] = color[0]; pixels[p+1] = color[1]; pixels[p+2] = color[2]; pixels[p+3] = 255;
  }
  return pixels;
}

export function analyzeFrame(pixels, index) {
  if (pixels.length !== WIDTH * HEIGHT * 4) throw new Error('Invalid frame dimensions.');
  return ['box', 'point'].map(kind => {
    let count = 0, sumX = 0, sumY = 0, minX = WIDTH, minY = HEIGHT, maxX = -1, maxY = -1;
    for (let p = 0; p < pixels.length; p += 4) {
      const r = pixels[p], g = pixels[p+1], b = pixels[p+2];
      const matches = kind === 'box' ? r > 180 && g < 100 && b < 100 : g > 180 && r < 100 && b < 100;
      if (!matches) continue;
      const x = (p / 4) % WIDTH, y = Math.floor(p / 4 / WIDTH);
      count++; sumX += x + .5; sumY += y + .5;
      minX = Math.min(minX,x); minY = Math.min(minY,y); maxX = Math.max(maxX,x+1); maxY = Math.max(maxY,y+1);
    }
    const row = Object.fromEntries(FIELDS.map(key => [key, '']));
    Object.assign(row, {frame_index:index,timestamp_sec:index/30,frame_width:WIDTH,frame_height:HEIGHT,
      adapter:`demo_${kind}`,kind:count ? kind : 'empty'});
    if (count) {
      Object.assign(row, {prediction_index:0,label:kind === 'box' ? 'red_region' : 'green_center',
        visible:kind === 'point' ? 1 : '',x1:kind === 'box' ? minX : sumX/count,
        y1:kind === 'box' ? minY : sumY/count,x2:kind === 'box' ? maxX : sumX/count,
        y2:kind === 'box' ? maxY : sumY/count});
      for (const key of ['x1','y1','x2','y2']) {
        row[key] = Number(row[key].toFixed(4));
        row[key+'_norm'] = Number((row[key] / (key[0] === 'x' ? WIDTH : HEIGHT)).toFixed(6));
      }
    }
    return row;
  });
}

export function toCSV(rows) {
  const cell = value => `"${String(value ?? '').replaceAll('"','""')}"`;
  return [FIELDS.join(','), ...rows.map(row => FIELDS.map(key => cell(row[key])).join(','))].join('\r\n') + '\r\n';
}
