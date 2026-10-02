import * as T from './vendor/three.module.js';

// Small procedural grain maps; no image files or network requests are needed.
export function makeSurfaceMaps(){
  const maps=new Map();let seed=901;const rnd=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296};
  function make(kind){const size=128,data=new Uint8Array(size*size*4);for(let y=0;y<size;y++)for(let x=0;x<size;x++){let value;if(kind==='wood'){value=205+Math.sin(x*.16+Math.sin(y*.04)*.9)*17+Math.sin(x*.81+y*.02)*7+(rnd()-.5)*18;if(x%31===0)value-=24}else if(kind==='stone'){value=222+(rnd()-.5)*35+Math.sin(x*.11)*Math.sin(y*.14)*9}else if(kind==='cloth'){value=218+((x+y)%2?11:-11)+(rnd()-.5)*8}else{value=238+(rnd()-.5)*18}const i=(y*size+x)*4;data[i]=data[i+1]=data[i+2]=Math.max(0,Math.min(255,value));data[i+3]=255}let t=new T.DataTexture(data,size,size,T.RGBAFormat);t.wrapS=t.wrapT=T.RepeatWrapping;t.minFilter=T.LinearMipmapLinearFilter;t.magFilter=T.LinearFilter;t.generateMipmaps=true;t.needsUpdate=true;t.colorSpace=T.SRGBColorSpace;maps.set(kind,t);return t}
  return {get(kind){return maps.get(kind)||make(kind)},dispose(){maps.forEach(m=>m.dispose())}};
}
