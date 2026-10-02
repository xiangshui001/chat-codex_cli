import * as T from './vendor/three.module.js';
import {addDetails} from './details.js';
import {addInteriorDetails} from './interior.js';
import {makeSurfaceMaps} from './surfaces.js';

/** Procedural reconstruction of the six supplied references. All visible architecture is voxel geometry. */
export function buildArchitecture(scene) {
  const C={stone:'#e2d2ac',shade:'#cbbd9b',light:'#f1e4c4',edge:'#b6a484',blue:'#233f67',tile:'#314f73',tile2:'#3d5977',gold:'#d2a858',bright:'#edca79',wood:'#785135',wood2:'#946a42',dark:'#493322',paper:'#ede0b7',green:'#557347',leaf:'#709158',glass:'#96c6d1'};
  const root=new T.Group(),shell=new T.Group(),roof=new T.Group(),inside=new T.Group();scene.add(root);root.add(shell,roof,inside);
  const geometry=new T.BoxGeometry(1,1,1),materials=new Map(),batches=new Map(),solids=[],lights=[],voxelData=[];const surfaces=makeSurfaceMaps();let seed=18261,books=0;
  function rnd(){seed=(seed*1664525+1013904223)>>>0;return seed/4294967296}
  function material(c,type='normal'){
    const k=c+type;if(!materials.has(k)){
      const m=new T.MeshStandardMaterial({color:c,roughness:type==='metal'?.32:.8,metalness:type==='metal'?.72:0,emissive:type==='glow'?c:0,emissiveIntensity:type==='glow'?1.65:0,transparent:type==='glass',opacity:type==='glass'?.29:1,depthWrite:type!=='glass'});
      if(type==='normal'){
        const kind=[C.wood,C.wood2,C.dark,'#a47c4e','#a78051','#b08c5b'].includes(c)?'wood':[C.blue,'#405868'].includes(c)?'cloth':[C.paper,'#f5e9c8'].includes(c)?'paper':[C.stone,C.shade,C.light,C.edge,'#ded0ad','#e5d8b8','#dbcdaa','#eadcbb'].includes(c)?'stone':null;
        if(kind){m.map=surfaces.get(kind);m.bumpMap=m.map;m.bumpScale=kind==='wood'?.045:kind==='stone'?.038:.015;m.roughness=kind==='wood'?.72:.84}
      }
      materials.set(k,m);
    }return materials.get(k)
  }
  function b(x,y,z,w,h,d,c=C.stone,g=root,type='normal',rot=0){if(![x,y,z,w,h,d].every(Number.isFinite)||w<=0||h<=0||d<=0)throw Error('Invalid voxel');let key=g.uuid+c+type;if(!batches.has(key))batches.set(key,{group:g,material:material(c,type),items:[]});batches.get(key).items.push({x,y,z,w,h,d,rot});voxelData.push({x,y,z,w,h,d,c,type,layer:g===roof?'roof':g===shell?'shell':'interior',rot});}
  function solid(x,z,w,d,floor=0){solids.push({x,z,w,d,floor})}
  function panel(cx,cz,angle,g=root){const cs=Math.cos(angle),sn=Math.sin(angle);return (x,y,z,w,h,d,c,type='normal')=>b(cx+cs*x+sn*z,y,cz-sn*x+cs*z,w,h,d,c,g,type,angle)}
  const archY=(x,r,spring)=>spring+Math.sqrt(Math.max(0,4*r*r-(Math.abs(x)+r)**2));
  function arch(cx,z,base,width,height,angle=0,g=shell,frame=C.gold,pane=true){const p=panel(cx,z,angle,g),r=width/2,spring=base+height-Math.sqrt(3)*r;const step=.23;
    if(pane)for(let x=-r+.14;x<r-.12;x+=.24){let top=archY(x,r,spring);p(x,base+(top-base)/2,0,.245,top-base,.08,C.glass,'glass')}
    for(let s of [-1,1])p(s*r,base+(spring-base)/2,.12,.26,spring-base,.32,frame);
    for(let x=-r;x<=r+.05;x+=step)p(x,archY(x,r,spring),.12,.29,.29,.34,frame);
    p(0,base,.12,width+.6,.3,.4,C.shade);
    const count=width>5?4:2;
    if(pane)for(let j=1;j<count;j++){let x=-r+width*j/count,top=archY(x,r,spring)-.25;p(x,base+(top-base)/2,.15,.12,top-base,.15,frame)}
    if(pane)for(let y=base+2.2;y<spring;y+=2.8)p(0,y,.16,width,.09,.13,frame);
    if(pane&&width>5){const rr=width*.13,cy=base+height-rr*1.4;
      for(let a=0;a<Math.PI*2;a+=.16)p(Math.cos(a)*rr,cy+Math.sin(a)*rr,.2,.19,.19,.18,frame);
      for(let k=0;k<8;k++){let a=k*Math.PI/4;p(Math.cos(a)*rr*.48,cy+Math.sin(a)*rr*.48,.23,.15,.15,.16,C.bright)}
      for(let s of [-1,1]){let xx=s*width*.23,yy=spring+rr*.15;for(let a=0;a<Math.PI*2;a+=.22)p(xx+Math.cos(a)*rr*.7,yy+Math.sin(a)*rr*.7,.19,.15,.15,.16,frame)}
    }
  }
  function wallBay(cx,z,width,height,angle,base=0,opening=true,g=shell){const p=panel(cx,z,angle,g),openingWidth=Math.min(width-1.5,(height-2.4)*.9),r=openingWidth/2,wheight=height-2.4,wb=base+1.15,spring=wb+wheight-Math.sqrt(3)*r;
    p(0,base+.56,0,width,1.12,.58,C.stone);if(!opening){p(0,base+height/2,0,width,height,.55,C.stone);return}
    for(let x=-width/2+.16;x<width/2;x+=.32){let top=Math.abs(x)<r?archY(x,r,spring):base+.9;let h=base+height-top;if(h>0)p(x,top+h/2,0,.325,h,.58,rnd()>.72?C.shade:C.stone)}
    arch(cx,z,wb,openingWidth,wheight,angle,g,C.gold);
    for(let side of [-1,1]){p(side*(width/2-.12),base+height/2,.32,.42,height,.9,C.shade);p(side*(width/2-.12),base+1.3,.45,.7,2.6,1.2,C.light)}
    p(0,base+height,.24,width+.3,.3,1.05,C.light);
  }
  function spire(x,z,y,width,height,g=roof){for(let j=0;j<Math.ceil(height/.32);j++){let t=j/(height/.32),w=Math.max(.12,width*(1-t));b(x,y+j*.32,z,w,.34,w,j%3?C.blue:C.tile,g);for(let sx of [-1,1])for(let sz of [-1,1])b(x+sx*w/2,y+j*.32,z+sz*w/2,.12,.34,.12,C.gold,g)}b(x,y+height+.55,z,.1,1.25,.1,C.bright,g,'metal');b(x,y+height+.6,z,.5,.12,.12,C.bright,g,'metal')}
  function gable(x,z,width,depth,base,height){
    const roofPalette=[C.blue,C.tile,C.tile2,'#385575','#294666','#426080'];
    for(let side of [-1,1])for(let i=0;i<Math.ceil(width/.34/2);i++){
      const d=i*.34,yy=base+(width/2-d)/(width/2)*height;
      for(let zz=-depth/2;zz<depth/2;zz+=.64){const shift=i%2?.16:0;b(x+side*d,yy,z+zz+.29+shift,.36,.34,.66,roofPalette[Math.floor(rnd()*roofPalette.length)],roof);b(x+side*d,yy+.177,z+zz+.29+shift,.32,.015,.032,'#203a58',roof)}
      for(let zz of [-depth/2,depth/2]){b(x+side*d,yy+.1,z+zz,.39,.21,.32,C.gold,roof);b(x+side*d,yy-.12,z+zz,.32,.08,.29,C.wood,roof);if(i%3===0)b(x+side*d,yy-.37,z+zz,.22,.52,.2,C.wood2,roof)}
    }
    b(x,base+height+.1,z,.45,.38,depth+.6,C.bright,roof);
    for(let zz=-depth/2;zz<=depth/2;zz+=.8){b(x,base+height+.42,z+zz,.09,.65,.09,C.gold,roof);b(x,base+height+.77,z+zz,.38,.07,.08,C.gold,roof);b(x,base+height+.93,z+zz,.14,.14,.14,C.bright,roof)}
  }
  function ivy(x,y,z,height=5,spread=.5,g=root){for(let i=0;i<height/.28;i++){let yy=y-i*.28,xx=x+Math.sin(i*.85)*spread;b(xx,yy,z,.08,.3,.1,C.green,g);for(let k=0;k<2;k++){let px=xx+(rnd()-.5)*.7,pz=z+(rnd()-.5)*.25;b(px,yy+(rnd()-.5)*.2,pz,.25+rnd()*.18,.16,.28,[C.green,C.leaf,'#879c61'][Math.floor(rnd()*3)],g);if(rnd()<.055)b(px,yy+.1,pz,.17,.17,.17,rnd()>.5?'#ecdbbd':'#ae9ac7',g)}}}
  function rail(x,z,length,angle=0,y=.8,g=root){const p=panel(x,z,angle,g),top=g===inside?C.wood2:C.light,post=g===inside?C.wood:C.stone,edge=g===inside?C.gold:C.shade;p(0,y+1.15,0,length,.17,.32,top);p(0,y+.13,0,length,.2,.45,edge);for(let xx=-length/2;xx<=length/2;xx+=.53){p(xx,y+.65,0,.16,1,.19,post);p(xx,y+.52,0,.29,.2,.29,edge)}for(let xx of [-length/2,length/2]){p(xx,y+.8,0,.55,1.6,.55,post);p(xx,y+1.65,0,.72,.2,.72,top)}}
  function star(p,x,y,z,r){for(let k=0;k<8;k++){let a=k*Math.PI/4,len=k%2?r*.55:r;for(let t=.15;t<len;t+=.12)p(x+Math.sin(a)*t,y+Math.cos(a)*t,z,.12,.12,.06,C.bright,'metal')}}
  function banner(cx,z,y,width=1.8,length=5,angle=0,g=root){const p=panel(cx,z,angle,g);p(0,y,0,width,length,.08,C.blue);const bottom=y-length/2;for(let j=0;j<Math.ceil(width/.2/2);j++){let w=width-j*.4;if(w>0)p(0,bottom-j*.19,0,w,.22,.08,C.blue)}for(let s of [-1,1])p(s*(width/2-.07),y,.06,.075,length,.06,C.gold);p(0,y+length/2+.15,0,width+.7,.12,.13,C.gold);let rr=width*.34;for(let a=0;a<Math.PI*2;a+=.2)p(Math.cos(a)*rr,y+.65+Math.sin(a)*rr,.08,.095,.095,.05,C.gold);star(p,0,y+.65,.09,rr*.9);for(let a=1;a<5.4;a+=.2)p(Math.cos(a)*rr*.32,y-length*.28+Math.sin(a)*rr*.32,.09,.12,.12,.06,C.bright)}
  function lantern(x,y,z,size=.6,light=false,g=root){b(x,y-.48*size,z,.45*size,.14*size,.45*size,C.gold,g,'metal');b(x,y,z,.48*size,.65*size,.48*size,'#ffd989',g,'glow');for(let s of [-1,1])for(let t of [-1,1])b(x+s*.27*size,y,z+t*.27*size,.055*size,.86*size,.055*size,C.gold,g,'metal');b(x,y+.47*size,z,.65*size,.16*size,.65*size,C.gold,g);b(x,y+.65*size,z,.15*size,.3*size,.15*size,C.bright,g);if(light){let l=new T.PointLight('#ffc06e',12,13,2);l.position.set(x,y,z);scene.add(l);lights.push(l)}}
  function planter(x,z,y=1,size=1){b(x,y+.35*size,z,.75*size,.7*size,.75*size,C.shade);b(x,y+.7*size,z,.95*size,.15*size,.95*size,C.light);for(let i=0;i<14;i++){let xx=x+(rnd()-.5)*size,zz=z+(rnd()-.5)*size,yy=y+.85*size+rnd()*.6*size;b(xx,yy,zz,.3*size,.24*size,.32*size,C.leaf);if(i%3===0)b(xx,yy+.13*size,zz,.2*size,.17*size,.2*size,['#e8dccb','#b7a3ce','#c2b5df'][i%3])}}
  // An isolated plinth, entrance terrace and broad staircase; no surrounding city.
  b(0,-.35,-1,49,1.3,37,C.shade);b(0,.45,-1,48.4,.28,36.4,C.stone);for(let x=-24;x<=24;x++)for(let z=-18;z<=16;z++)if(Math.abs(x)>18||z>13)b(x,.63,z,.95,.09,.95,[C.stone,C.light,C.shade][Math.floor(rnd()*3)]);
  b(0,.73,-1,36.7,.18,31,C.wood);for(let x=-18;x<18;x++)for(let z=-16;z<14;z++)b(x+.5,.84,z+.5,.96,.06,.96,(x+z)%2?'#d6c4a4':'#e3d4b7',inside);
  for(let i=0;i<10;i++)b(0,.02+i*.075,22-i*.6,8,.15,.62,C.light);rail(-7,17,10,0,.75);rail(7,17,10,0,.75);for(let x of [-13,-7,7,13]){lantern(x,2.75,17,.95);planter(x+(x<0?1:-1),15,.75,1.3)}
  // Nave's front façade: doorway below the immense lancet window.
  for(let s of [-1,1])b(s*5.9,3.6,13,4.8,5.8,.7,C.stone,shell);
  arch(0,13,1,5.5,5.6,0,shell,C.shade,false);for(let x=-8.4;x<=8.4;x+=.35){let r=5.3,spring=6.9+13.7-Math.sqrt(3)*r,top=Math.abs(x)<r?archY(x,r,spring):6.9;let h=22-top;if(h>0)b(x,top+h/2,13,.36,h,.65,rnd()>.8?C.shade:C.stone,shell)}b(0,6.35,13,17.5,.65,.72,C.shade,shell);arch(0,13.4,6.9,10.6,13.7,0,shell);banner(-6.8,13.62,13,1.55,8,0,shell);banner(6.8,13.62,13,1.55,8,0,shell);
  // Open carved doors, set perpendicular to the entrance so entry remains walkable.
  for(let s of [-1,1]){const p=panel(s*2.7,13,s*-1.42,shell);p(s*1.1,3.1,0,2.2,4.5,.22,C.wood);p(s*1.1,3.1,.14,1.88,4.1,.08,C.dark);for(let yy of [1.3,3.0,4.9])p(s*1.1,yy,.22,1.98,.1,.1,C.gold);p(s*.35,3,.24,.18,.3,.08,C.bright)}
  b(0,5.9,13.62,6.4,.3,.72,C.wood2,shell);for(let x of [-3.8,3.8]){lantern(x,3.9,13.7,1,true);planter(x,14.4,.8,1.5)}
  // Gable stonework follows the pitched silhouette.
  for(let j=0;j<25;j++){let yy=22+j*.3,w=18*(1-j/25);if(w>.1){b(0,yy,13,w,.32,.62,C.stone,shell);b(0,yy,-16,w,.32,.62,C.stone,shell)}}
  // Huge rear window, with light streaming through the hall.
  for(let x=-8.5;x<8.7;x+=.35){let r=5.7,spring=1+19-Math.sqrt(3)*r,top=Math.abs(x)<r?archY(x,r,spring):1,h=22-top;if(h>0)b(x,top+h/2,-16,.36,h,.7,C.stone,shell)}b(0,.95,-16,18,.3,.7,C.shade,shell);arch(0,-16.4,1.2,11.4,18.6,Math.PI,shell);
  // Side wings and exterior buttresses with pinnacles.
  for(let s of [-1,1]){
    for(let z=-13;z<=11;z+=6)wallBay(s*18.2,z,6,16,s*Math.PI/2);
    for(let x of [s*12,s*16.5])wallBay(x,13,4.5,13,0);
    for(let x of [s*12,s*16.5])wallBay(x,-16,4.5,13,Math.PI);
    for(let z=-16;z<=14;z+=6){b(s*18.7,8.6,z,.9,15.5,1,C.shade,shell);b(s*18.7,1.6,z,1.35,2.7,1.4,C.light,shell);b(s*18.7,16.1,z,1.3,.35,1.5,C.light,shell);spire(s*18.7,z,16.5,1.05,3.4)}
    gable(s*13.9,-1.5,10.5,30,15.7,4.6);
    for(let z of [-13,-7,-1,5,11]){b(s*9,18.7,z,.65,7,.6,C.stone,shell);wallBay(s*9,z,6,5.8,s*Math.PI/2,16.1,true,shell)}
    for(let x of [s*8.5,s*18.4]){ivy(x,19,13.78,14,.28,shell);spire(x,13,20.9,1.1,4.1)}
  }
  gable(0,-1.5,19.3,31.5,22,8.2);
  // Two attached towers, not separate buildings.
  for(let [x,z] of [[-20.5,8],[20.5,-11]]){for(let y=1;y<25;y+=6){for(let a of [0,Math.PI/2,Math.PI,-Math.PI/2]){let xx=x+Math.sin(a)*2.8,zz=z+Math.cos(a)*2.8;wallBay(xx,zz,5.6,6,a,y,true,shell)}b(x,y,z,6.2,.28,6.2,C.light,shell)}for(let sx of [-1,1])for(let sz of [-1,1]){b(x+sx*2.75,13.5,z+sz*2.75,.45,25,.45,C.shade,shell);spire(x+sx*2.8,z+sz*2.8,26,1.1,4)}b(x,26.2,z,6.8,.35,6.8,C.gold,roof);spire(x,z,26.5,6.9,13.5);banner(x,z+3.1,13.5,2.5,12,0,shell);ivy(x-2.8,24,z+3.2,21,.27,shell)}
  // Interior stone columns, vaulted ribs and wooden trusses.
  function column(x,z){b(x,1.2,z,1.15,.65,1.15,C.shade,inside);b(x,10.1,z,.67,18,.67,C.stone,inside);for(let y of [7.9,15,19.5]){b(x,y,z,1.1,.3,1.1,C.shade,inside);b(x,y+.3,z,1.4,.25,1.4,C.light,inside)}solid(x,z,1.1,1.1,0);solid(x,z,1.1,1.1,1);solid(x,z,1.1,1.1,2)}
  for(let x of [-8.2,8.2])for(let z of [-12,-6,0,6,11])column(x,z);
  for(let z of [-12,-6,0,6,11]){for(let i=0;i<44;i++){let xx=-8.2+i*.38,yy=archY(xx,8.2,9.2);b(xx,yy,z,.5,.42,.47,C.wood2,inside)}for(let s of [-1,1])for(let i=0;i<24;i++){let xx=s*i*.38,yy=29.6-i*.33;b(xx,yy,z,.5,.45,.4,C.wood2,inside)}b(0,21.7,z,17,.38,.42,C.wood,inside)}
  // U-shaped open galleries at two levels; a continuous walkable floor.
  const floorHeights=[.9,7.9,14.9];
  for(let [level,y] of [[1,7.9],[2,14.9]]){for(let s of [-1,1]){if(s<0)b(-13.2,y-.22,-1.5,10,.44,29,C.wood,inside);else{b(10.15,y-.22,-1.5,3.9,.44,29,C.wood,inside);b(16.45,y-.22,-1.5,3.5,.44,29,C.wood,inside);b(13.35,y-.22,-10,2.5,.44,12,C.wood,inside);b(13.35,y-.22,11.6,2.5,.44,3.2,C.wood,inside)}rail(s*8.2,-1.5,26,-Math.PI/2,y,inside);for(let z of [-12,-6,0,6]){if(s>0&&z===6)continue;ivy(s*8.35,y+.75,z,3,.28,inside)}}b(0,y-.22,-13.5,16.5,.44,4.2,C.wood,inside);rail(0,-11.4,16,0,y,inside);}
  // Right-side straight stair runs: 7 metres rise / 14 metres run.
  const stairs=[{x:13.5,zStart:10,zEnd:-4,y0:.9,y1:7.9,level:0},{x:13.5,zStart:10,zEnd:-4,y0:7.9,y1:14.9,level:1}];
  for(const st of stairs){for(let i=0;i<35;i++){let z=st.zStart-(i+.5)*.4,y=st.y0+(i+1)*.2;b(st.x,y-.1,z,2.5,.2,.42,C.wood2,inside);b(st.x,y+.015,z,1.85,.045,.41,C.blue,inside);for(let s of [-1,1]){b(st.x+s*1.26,y+.68,z,.1,1.32,.1,C.wood,inside);b(st.x+s*1.26,y+1.3,z,.17,.16,.48,C.wood2,inside)}if(i%7===0){lantern(st.x-1.35,y+1.72,z,.58,false,inside);b(st.x,y+.05,z,1.9,.02,.06,C.gold,inside)}}
    // The gallery is cut away beneath the next flight so walkers do not clip through a ceiling.
  }
  // Dense wooden wall libraries on all three floors.
  const bookPalette=['#334b59','#405868','#7c5845','#a17b4d','#536557','#a49673','#683e38','#b08c5b'];
  function shelf(x,z,w,angle,y0,level){
    // Low shelves fit beneath the side-wing attic roofs; the central rear library remains tall.
    const low=level===2&&Math.abs(x)>9,height=low?2.2:6.06,rowCount=low?2:6,rowStep=low?.65:.8,p=panel(x,z,angle,inside);
    p(0,y0+(height-.66)/2,0,w,height-.66,.33,C.dark);
    for(let side of [-1,1]){p(side*w/2,y0+(height-.46)/2,.5,.22,height-.46,1.1,C.wood2);p(side*w/2,y0+height-.39,.52,.32,.22,1.2,C.gold)}
    for(let k=0;k<rowCount;k++){let y=y0+.78+k*rowStep;p(0,y,.48,w+.2,.16,1.12,C.wood2);let xx=-w/2+.18;while(xx<w/2-.2){let bw=.14+rnd()*.16,bh=low?.4+rnd()*.14:.52+rnd()*.25,c=bookPalette[Math.floor(rnd()*bookPalette.length)];p(xx+bw/2,y+.1+bh/2,.56,bw*.9,bh,.57,c);for(let yy of [bh*.3+.1,bh*.74+.1])p(xx+bw/2,y+yy,.856,bw*.67,.035,.018,C.gold);if(rnd()>.6)p(xx+bw/2,y+.1+bh*.5,.86,bw*.45,.06,.015,C.paper);xx+=bw;books++}}
    for(let side of [-1,1]){let xx=side*w*.25;p(xx,y0+.41,.79,w*.45,.57,.1,C.wood2);p(xx,y0+.41,.851,w*.38,.43,.045,C.dark);p(xx,y0+.41,.89,w*.33,.38,.02,C.wood);p(xx-side*.22,y0+.45,.94,.11,.065,.08,C.gold,'metal');for(let j=0;j<(low?3:10);j++){p(side*w/2,y0+.94+j*(low?.28:.43),.87,.3,.14,.19,C.wood2);p(side*w/2,y0+.96+j*(low?.28:.43),.98,.14,.08,.07,C.gold)}}
    for(let xx=-w/2;xx<w/2;xx+=.22){p(xx,y0+height-.12,.46,.16,.16,.16,C.gold);p(xx,y0+height-.26,.96,.14,.16,.13,C.wood)}
    p(0,y0+height-.1,.42,w+.55,.12,1.25,C.wood);p(0,y0+height-.31,.42,w+.42,.08,1.2,C.gold);
    p(0,y0+height-.57,.99,.8,.21,.06,C.blue);for(let xx=-.3;xx<.4;xx+=.12)p(xx,y0+height-.56,1.027,.06,.06,.016,C.gold);
    p(0,y0+height-.36,.48,w+.4,.24,1.2,C.wood2);solid(x+Math.sin(angle)*.5,z+Math.cos(angle)*.5,Math.abs(Math.sin(angle))>.5?1.55:w+.4,Math.abs(Math.sin(angle))>.5?w+.4:1.55,level);
  }
  for(let [level,y] of floorHeights.entries()){for(let s of [-1,1])for(let z of [-12,-6,0,6,10.5])shelf(s*17.3,z,z===10.5?3:4.7,-s*Math.PI/2,y,level);for(let x of [-12,-6,6,12])shelf(x,-15.3,level===2&&Math.abs(x)>9?3:4.8,0,y,level)}
  // Desks, star-pattern runners, chairs, open volumes and armillary spheres.
  function armillary(x,y,z,r=.55){b(x,y-.5,z,.7,.14,.7,C.gold,inside,'metal');b(x,y-.2,z,.15,.6,.15,C.gold,inside,'metal');for(let a=0;a<6.28;a+=.14){b(x+Math.cos(a)*r,y+.6+Math.sin(a)*r,z,.09,.09,.09,C.gold,inside,'metal');b(x,y+.6+Math.sin(a)*r,z+Math.cos(a)*r,.09,.09,.09,C.gold,inside,'metal');b(x+Math.cos(a)*r,y+.6,z+Math.sin(a)*r,.09,.09,.09,C.bright,inside,'metal')}b(x,y+.6,z,.27,.27,.27,C.bright,inside,'metal')}
  function chair(x,z,y0,angle,level){const p=panel(x,z,angle,inside);p(0,y0+.82,0,.9,.16,.9,C.wood2);for(let xx of [-.34,.34])for(let zz of [-.34,.34])p(xx,y0+.42,zz,.12,.76,.12,C.wood);p(0,y0+1.5,-.35,.98,1.5,.17,C.wood2);p(0,y0+1.5,-.24,.65,1.25,.05,C.blue);star(p,0,y0+1.65,-.2,.24);solid(x,z,1,1,level)}
  function desk(x,z,y0,level=0,w=3.6){b(x,y0+1.38,z,w,.21,2.1,C.wood2,inside);for(let xx of [-w/2+.25,w/2-.25])for(let zz of [-.78,.78]){b(x+xx,y0+.65,z+zz,.2,1.25,.2,C.wood,inside);b(x+xx,y0+.2,z+zz,.33,.18,.33,C.gold,inside)}b(x,y0+1.5,z,1.4,.03,2.12,C.blue,inside);for(let s of [-1,1])b(x+s*.65,y0+1.52,z,.045,.025,2.1,C.gold,inside);
    let p=panel(x,z,0,inside);for(let side of [-1,1]){b(x+side*.3,y0+1.59,z+.25,.58,.12,.7,C.paper,inside);b(x+side*.3,y0+1.64,z+.25,.55,.02,.67,'#f5e9c8',inside);for(let j=0;j<5;j++)b(x+side*.3,y0+1.656,z+.02+j*.1,.42,.008,.012,'#a89a77',inside)}b(x+1.05,y0+1.6,z-.35,.73,.2,.55,C.blue,inside);b(x+1.05,y0+1.77,z-.35,.65,.13,.52,'#a78051',inside);lantern(x-w/2+.55,y0+1.98,z-.3,.65,false,inside);armillary(x+.9,y0+1.5,z+.35,.38);// Drawer panels and carved aprons under the desktop.
    for(let side of [-1,1]){b(x+side*w*.26,y0+1.16,z+1.07,w*.39,.26,.08,C.wood,inside);b(x+side*w*.26,y0+1.16,z+1.12,w*.31,.16,.03,C.wood2,inside);b(x+side*w*.26,y0+1.16,z+1.16,.15,.07,.05,C.gold,inside,'metal')}
    for(let j=0;j<11;j++)b(x-w/2+.22+j*(w-.44)/10,y0+1.02,z+1.06,.07,.1,.07,C.gold,inside);
    // Ink bottle, quill, teacup, paper scrolls and a miniature bookmark.
    b(x+.65,y0+1.65,z-.78,.21,.25,.21,'#24444a',inside);b(x+.65,y0+1.81,z-.78,.14,.06,.14,C.gold,inside,'metal');
    for(let j=0;j<10;j++){b(x+.65+j*.021,y0+1.87+j*.038,z-.78,.035,.045,.03,C.paper,inside);if(j>4)b(x+.67+j*.021,y0+1.87+j*.038,z-.78,.105,.035,.03,'#f3e5c9',inside)}
    const cupX=x+.35,cupZ=z+.67,cy=y0+1.58;b(cupX,cy,cupZ,.35,.04,.35,C.paper,inside);for(let j=0;j<16;j++){let a=j*Math.PI/8;b(cupX+Math.cos(a)*.12,cy+.13,cupZ+Math.sin(a)*.12,.055,.2,.055,C.paper,inside);b(cupX+Math.cos(a)*.12,cy+.25,cupZ+Math.sin(a)*.12,.057,.025,.057,C.gold,inside)}b(cupX,cy+.15,cupZ,.19,.02,.19,'#785334',inside);for(let j=0;j<6;j++)b(cupX+.19,cy+.06+j*.03,cupZ,.04,.025,.05,C.paper,inside);
    b(x-w/2+.53,y0+1.58,z+.71,.47,.17,.12,C.paper,inside);b(x-w/2+.53,y0+1.67,z+.71,.42,.05,.14,'#f3e5c9',inside);b(x-.18,y0+1.666,z+.4,.055,.013,.47,'#ac5b44',inside);
    for(let j=0;j<3;j++){b(x+w/2-.55,y0+1.6+j*.13,z+.77,.6,.11,.36,['#55716c','#976346',C.blue][j],inside);b(x+w/2-.55,y0+1.6+j*.13,z+.95,.44,.065,.02,C.paper,inside)}
    chair(x,z+1.65,y0,Math.PI,level);solid(x,z,w,2.2,level)
  }
  for(let z of [-7,-1,5])for(let x of [-4.2,4.2])desk(x,z,.9,0);
  for(let [level,y] of [[1,7.9],[2,14.9]])for(let z of [-6,4])desk(-12.8,z,y,level,2.8);
  // Blue carpet, eight-point compass medallions, and entrance lecterns.
  b(0,.91,-1,3,.035,27,C.blue,inside);for(let s of [-1,1])b(s*1.4,.93,-1,.07,.02,27,C.gold,inside);
  for(let z of [-9,-2,5,10]){for(let a=0;a<6.28;a+=.17)b(Math.cos(a)*.88,.948,z+Math.sin(a)*.88,.1,.018,.1,C.gold,inside);for(let k=0;k<8;k++){let a=k*Math.PI/4;for(let t=.1;t<.78;t+=.1)b(Math.sin(a)*t,.953,z+Math.cos(a)*t,.1,.02,.1,C.bright,inside)}}
  for(let x of [-5.2,5.2]){b(x,1.6,10.3,1.8,1.45,1.2,C.wood,inside);b(x,2.36,10.3,2,.2,1.4,C.wood2,inside);armillary(x,2.45,10.3,.7);solid(x,10.3,2,1.5,0)}
  // Two tiered candle rings suspended from the high timber vault.
  for(let z of [-7,4]){let y=15.9,r=2.8;b(0,22,z,.07,6.3,.07,C.gold,inside,'metal');for(let rr of [r,r*.65]){let yy=rr===r?y:y-1.5;for(let a=0;a<6.28;a+=.07)b(Math.cos(a)*rr,yy,z+Math.sin(a)*rr,.21,.14,.21,C.gold,inside,'metal');for(let k=0;k<10;k++){let a=k*Math.PI/5,x=Math.cos(a)*rr,zz=z+Math.sin(a)*rr;b(x,yy+.35,zz,.15,.6,.15,'#efdaab',inside);b(x,yy+.72,zz,.12,.19,.12,'#ffdd85',inside,'glow');if(k%2===0)for(let j=0;j<10;j++){let t=j/10;b(x*(1-t),yy+t*3.4,zz+(z-zz)*t,.06,.15,.06,C.gold,inside,'metal')}}}let l=new T.PointLight('#ffc779',90,36,2);l.position.set(0,y-1,z);scene.add(l);lights.push(l)}
  for(let x of [-8.2,8.2])for(let z of [-10,-4,2,8]){lantern(x,5.4,z,.85,z===2,inside);banner(x*.91,z,16,1.4,6,-Math.sign(x)*Math.PI/2,inside);ivy(x,13,z+.3,5,.3,inside)}
  for(let x of [-7,7])for(let z of [-11,9])planter(x,z,.95,1.15);
  for(let [y,z] of [[8,-10],[15,-10],[8,10],[15,10]]){planter(-8.4,z,y,1);planter(8.4,z,y,1)}
  for(let x of [-12,12]){ivy(x,12.8,13.8,10,.4,shell);banner(x,13.8,7.5,1.4,5,0,shell)}
  addDetails({C,b,panel,archY,shell,roof,inside,root,rnd,lantern,planter,ivy,solid,banner});
  books+=addInteriorDetails({C,b,panel,inside,shell,archY,solid}).books;
  let voxelCount=0;for(let v of batches.values()){let mesh=new T.InstancedMesh(geometry,v.material,v.items.length),o=new T.Object3D();for(let [i,p] of v.items.entries()){o.position.set(p.x,p.y,p.z);o.scale.set(p.w,p.h,p.d);o.rotation.set(0,p.rot,0);o.updateMatrix();mesh.setMatrixAt(i,o.matrix)}mesh.castShadow=!v.material.transparent&&v.material.emissiveIntensity!==1.65;mesh.receiveShadow=true;v.group.add(mesh);voxelCount+=v.items.length;mesh.computeBoundingSphere()}
  const haloMaterials=[];
  for(let group of [root,shell,inside,roof]){
    const pos=[];for(let batch of batches.values())if(batch.group===group&&batch.material.emissiveIntensity===1.65)for(let p of batch.items)pos.push(p.x,p.y,p.z);
    if(!pos.length)continue;const pg=new T.BufferGeometry();pg.setAttribute('position',new T.Float32BufferAttribute(pos,3));
    const pm=new T.ShaderMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending,uniforms:{pulse:{value:1}},vertexShader:'uniform float pulse;void main(){vec4 mv=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=min(160.0,700.0/max(1.0,-mv.z))*pulse;}',fragmentShader:'void main(){float d=length(gl_PointCoord-vec2(.5));float a=pow(max(0.0,1.0-d*2.0),3.0)*.28;gl_FragColor=vec4(1.0,.61,.22,a);}' });
    const halo=new T.Points(pg,pm);halo.renderOrder=3;group.add(halo);haloMaterials.push({pm,pg});
  }
  const dustGeometry=new T.BufferGeometry(),dustPos=new Float32Array(180*3);for(let i=0;i<180;i++){dustPos[i*3]=(rnd()-.5)*16;dustPos[i*3+1]=1+rnd()*19;dustPos[i*3+2]=(rnd()-.5)*27}dustGeometry.setAttribute('position',new T.BufferAttribute(dustPos,3));const dustMaterial=new T.PointsMaterial({color:'#ffe4b2',size:.045,transparent:true,opacity:.5,depthWrite:false});const dust=new T.Points(dustGeometry,dustMaterial);inside.add(dust);
  // Floor sampling determines whether a proposed walking step has support.
  function sampleFloor(x,z,previousY){if(x<-17.65||x>17.65||z<-15.35||z>12.1)return null;
    let level=Math.round((previousY-.9)/7);level=Math.max(0,Math.min(2,level));
    for(let st of stairs){if(Math.abs(x-st.x)<1.12&&z>=st.zEnd-.25&&z<=st.zStart+.3){let progress=T.MathUtils.clamp((st.zStart-z)/(st.zStart-st.zEnd),0,1);let y=st.y0+progress*7;if(Math.abs(previousY-y)<.55)return {y,level:progress>.96?st.level+1:st.level,stairs:true}}}
    if(Math.abs(x-13.5)<1.38&&z>-4.25&&z<10.3)return null;let y=floorHeights[level];if(Math.abs(previousY-y)>.46)return null;if(level>0&&!(Math.abs(x)>=8.65||z<=-11.4))return null;
    if(solids.some(o=>o.floor===level&&Math.abs(x-o.x)<o.w/2+.24&&Math.abs(z-o.z)<o.d/2+.24))return null;return {y,level,stairs:false};
  }
  function setCutaway(v){roof.visible=!v;shell.visible=!v}
  let flameTime=0;function update(dt){flameTime+=dt;haloMaterials.forEach(({pm},i)=>pm.uniforms.pulse.value=.97+Math.sin(flameTime*2.2+i)*.025);for(let i=0;i<180;i++){dustPos[i*3+1]+=.03*dt;if(dustPos[i*3+1]>20)dustPos[i*3+1]=1}dustGeometry.attributes.position.needsUpdate=true}
  function dispose(){root.traverse(o=>{if(o.isInstancedMesh)o.dispose()});geometry.dispose();dustGeometry.dispose();dustMaterial.dispose();materials.forEach(m=>m.dispose());surfaces.dispose();haloMaterials.forEach(({pm,pg})=>{pm.dispose();pg.dispose()});root.removeFromParent();lights.forEach(l=>l.removeFromParent())}
  return {root,roof,shell,inside,lights,solids,stairs,floorHeights,sampleFloor,setCutaway,update,dispose,stats:{voxels:voxelCount,books,drawCalls:batches.size},voxelData};
}
