import test from 'node:test';
import assert from 'node:assert/strict';
import {generateFrame,analyzeFrame,toCSV,FIELDS,WIDTH,HEIGHT} from '../../demo/engine.mjs';
test('known scene positions, source bounds, and normalized coordinates',()=>{
 const [box,point]=analyzeFrame(generateFrame(0),0);
 assert.deepEqual([box.x1,box.y1,box.x2,box.y2],[35,80,121,146]);
 assert.deepEqual([point.x1,point.y1,point.x2,point.y2],[320.5,270.5,320.5,270.5]);
 assert.equal(box.x1_norm,Number((35/640).toFixed(6)));
 assert.equal(point.confidence,'');
});
test('detectors read pixels independently of frame number',()=>{
 const frame = new Uint8ClampedArray(WIDTH*HEIGHT*4);
 let p=(10*WIDTH+20)*4; frame[p]=235;
 p=(30*WIDTH+40)*4; frame[p+1]=225;
 const [box,point]=analyzeFrame(frame,55);
 assert.deepEqual([box.x1,box.y1,box.x2,box.y2],[20,10,21,11]);
 assert.deepEqual([point.x1,point.y1],[40.5,30.5]);
});
test('independent gaps, empty rows, and complete CSV',()=>{
 const rows=[];
 for(let i=0;i<120;i++) rows.push(...analyzeFrame(generateFrame(i),i));
 assert.equal(rows.length,240);
 assert.equal(rows.filter(r=>r.kind==='box').length,100);
 assert.equal(rows.filter(r=>r.kind==='point').length,80);
 assert.equal(rows.filter(r=>r.kind==='empty').length,60);
 assert.deepEqual(rows.slice(110,112).map(r=>r.kind),['empty','empty']);
 assert.equal(rows[111].x1,'');
 const csv=toCSV(rows).trim().split('\r\n');
 assert.equal(csv.length,241); assert.equal(csv[0],FIELDS.join(','));
});
