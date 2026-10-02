/** Fine architectural dressing; uses the same instanced voxel palette as the main model. */
export function addDetails(A){
  const {C,b,panel,archY,shell,roof,inside,root,rnd,lantern,planter,ivy,solid,banner}=A;
  const mortar='#b8aa8d',stoneColors=['#ded0ad','#e5d8b8','#dbcdaa','#eadcbb'],oak='#a47c4e';
  function ring(p,x,y,z,r,c=C.gold,step=.09,thick=.09){for(let a=0;a<Math.PI*2;a+=step)p(x+Math.cos(a)*r,y+Math.sin(a)*r,z,thick,thick,.11,c,'metal')}
  function rosette(p,x,y,z,r){ring(p,x,y,z,r,C.shade,.055,.18);ring(p,x,y,z,r*.87,C.gold,.06,.1);for(let k=0;k<8;k++){let a=k*Math.PI/4;for(let d=.12;d<r*.84;d+=.095)p(x+Math.cos(a)*d,y+Math.sin(a)*d,z+.025,.085,.085,.1,C.gold,'metal');let px=x+Math.cos(a)*r*.52,py=y+Math.sin(a)*r*.52;ring(p,px,py,z+.035,r*.2,C.bright,.15,.067)}ring(p,x,y,z+.05,r*.17,C.gold,.1,.09)}
  function border(p,x,base,z,w,h){let r=w/2,spring=base+h-Math.sqrt(3)*r;for(let s of [-1,1]){p(x+s*r,base+(spring-base)/2,z,.14,spring-base,.23,C.shade);p(x+s*(r+.17),base+(spring-base)/2,z-.06,.14,spring-base,.16,C.light)}for(let xx=-r;xx<=r;xx+=.12){let yy=archY(xx,r,spring);p(x+xx,yy,z,.15,.16,.24,C.light);if(Math.round((xx+r)/.12)%4===0)p(x+xx,yy+.18,z,.11,.18,.15,C.gold)}}
  // Joints and individual stone faces, following openings rather than covering them.
  function stoneSkin(p,width,height,base,z,predicate){for(let row=0;row<height/.46;row++){let yy=base+row*.46+.22;for(let xx=-width/2+(row%2?.45:0);xx<width/2;xx+=.9){if(!predicate(xx,yy))continue;p(xx,yy,z,.865,.42,.065,stoneColors[Math.floor(rnd()*stoneColors.length)]);if(rnd()<.035)p(xx+.12,yy+.035,z+.038,.12,.015,.009,mortar)}}}
  let front=panel(0,13.39,0,shell);stoneSkin(front,17,21.15,.8,.09,(x,y)=>{if(y<6.4&&Math.abs(x)<2.8)return false;let spring=20.6-Math.sqrt(3)*5.3;if(y>=6.9&&Math.abs(x)<5.4&&y<archY(x,5.3,spring)+.14)return false;return true});stoneSkin(front,18,7,22,.09,(x,y)=>Math.abs(x)<9*(1-(y-22)/7.5));
  border(front,0,.94,.2,6.2,6.2);border(front,0,6.83,.28,11.15,14.05);
  // Tall central stone window: small lancets, quatrefoils and leaded panels.
  for(let [x,y,r] of [[0,19.13,1.34],[-2.42,15.65,.96],[2.42,15.65,.96]])rosette(front,x,y,.34,r);
  for(let x of [-3.9,-1.3,1.3,3.9]){border(front,x,7.05,.35,2.45,8.2);for(let y=7.7;y<13.8;y+=1.15){front(x-.52,y,.36,.04,.67,.07,C.gold);front(x+.52,y,.36,.04,.67,.07,C.gold)}}
  for(let yy=-1.6;yy<=1.6;yy+=.16)front(0,25.24+yy,.14,2*Math.sqrt(Math.max(.01,1.65**2-yy**2)),.17,.1,C.blue);
  rosette(front,0,25.24,.24,1.7);front(0,28.2,.15,.18,.6,.2,C.gold);front(0,28.2,.15,.7,.13,.2,C.gold);
  // Gable timber work, carved cornices, and brackets beneath the eaves.
  for(let s of [-1,1])for(let j=0;j<34;j++){let x=s*j*.245,y=29.3-j*.213;front(x,y,.25,.3,.31,.24,C.wood2);front(x,y-.26,.18,.25,.35,.18,C.wood)}for(let x=-7;x<=7;x+=1.35){front(x,22.1,.35,.45,.2,.7,C.wood);front(x,21.78,.31,.35,.45,.54,C.wood2)}
  for(let s of [-1,1]){let p=panel(s*18.56,-1.6,s*Math.PI/2,shell);for(let z of [-13,-7,-1,5,11]){let q=panel(s*18.5,z,s*Math.PI/2,shell);for(let y=1.2;y<15.7;y+=.51){q(-2.62,y,.18,.7,.46,.065,stoneColors[Math.floor(rnd()*4)]);q(2.62,y,.18,.7,.46,.065,stoneColors[Math.floor(rnd()*4)])}border(q,0,1.13,.19,4.64,13.64);for(let k of [-1,1]){q(k*2.6,8,.28,.16,13,.19,C.light);for(let y of [2.8,7.9,13.1])q(k*2.6,y,.33,.54,.18,.55,C.shade)}}
    for(let y of [.9,7.9,15.8]){p(0,y,.17,30,.16,.3,C.light);p(0,y+.22,.24,30,.1,.4,C.shade);for(let x=-14.5;x<15;x+=.6)p(x,y+.38,.27,.16,.13,.26,C.gold)}
    // Flying buttresses bridge the low side roofs to the nave clerestory.
    for(let z of [-13,-7,-1,5,11]){if((s<0&&z>4)||(s>0&&z<-6))continue;for(let j=0;j<44;j++){let t=j/43,x=s*(9.4+9.35*t),y=21.15-7.9*t+1.7*Math.sin(t*Math.PI);b(x,y,z,.3,.45,.74,C.stone,shell);b(x,y+.31,z,.32,.12,.9,C.light,shell);b(x,y-.32,z,.28,.14,.52,C.shade,shell)}b(s*19.2,6.7,z,.8,12,.84,C.shade,shell);for(let yy of [1.3,6.4,12.4])b(s*19.2,yy,z,1.15,.27,1.2,C.light,shell)}
    // Roof dormers, each with a pointed golden window and tiny gable cap.
    for(let z of [-10,-2,6]){let q=panel(s*16.3,z,s*Math.PI/2,roof);q(0,18.88,0,1.75,2.4,.45,C.stone);q(0,18.9,.26,1.22,1.85,.05,C.blue);border(q,0,18.04,.32,1.3,1.9);q(0,18.9,.34,.055,1.7,.09,C.gold);for(let j=0;j<12;j++){let w=2-j*.15;let yy=20.12+j*.09;q(0,yy,-.4,w,.12,1.65,j%2?C.tile:C.blue);q(-w/2,yy,.44,.14,.14,.22,C.gold);q(w/2,yy,.44,.14,.14,.22,C.gold)}q(0,21.36,.4,.08,.6,.13,C.bright)}
  }
  // Tower bands, niches, gargoyle-like brackets, and rooftop balustrades.
  for(let [x,z] of [[-20.5,8],[20.5,-11]])for(let a of [0,Math.PI/2,Math.PI,Math.PI*1.5]){const q=panel(x+Math.sin(a)*3.14,z+Math.cos(a)*3.14,a,shell);for(let y of [6.9,12.9,18.9,25.5]){q(0,y,0,6.4,.18,.6,C.light);q(0,y-.2,.02,6.2,.1,.48,C.shade);for(let xx=-2.6;xx<=2.6;xx+=.57){q(xx,y+.39,.15,.18,.65,.2,C.stone);q(xx,y+.71,.14,.57,.12,.27,C.gold)}}for(let xx of [-2.62,2.62])for(let y=2;y<25;y+=1.1){q(xx,y,.04,.61,.58,.12,C.shade);q(xx,y+.36,.1,.34,.18,.24,C.light)}for(let xx of [-2.2,2.2]){q(xx,25.9,.42,.65,.45,.95,C.shade);q(xx,26.15,.8,.32,.3,.52,C.light);q(xx,26.32,1.03,.25,.15,.25,C.gold)}}
  // Entrance niches, door fittings, and a carved crest over the porch.
  for(let s of [-1,1]){let q=panel(s*5.9,13.57,0,shell);border(q,0,1.42,.15,1.55,3.4);q(0,2.75,.12,1.28,2.4,.08,C.blue);q(0,2.4,.3,.65,.2,.45,C.gold);q(0,2.86,.3,.25,.65,.25,C.light);q(0,3.25,.3,.35,.35,.3,C.light);lantern(s*6.8,5.9,13.96,.5,false,shell);
    let door=panel(s*2.7,13,s*-1.42,shell);for(let y of [1.6,3.1,4.5])for(let xx of [.55,1.7]){door(s*xx,y,.255,.1,.1,.07,C.bright,'metal')}for(let j=0;j<18;j++){let yy=1.22+j*.22;door(s*1.1+Math.sin(j*.8)*.27,yy,.26,.06,.18,.06,C.gold,'metal')}ring(door,s*.35,3,.32,.18,C.bright,.2,.05)}
  rosette(front,0,6.22,.58,.44);for(let s of [-1,1])for(let t=0;t<18;t++)front(s*(.7+t*.14),6.22+Math.sin(t*.25)*.16,.51,.13,.065,.07,C.gold);
  // Lush vines follow exterior columns and balcony flower ledges.
  for(let s of [-1,1]){for(let z of [-14,-8,-2,4,10]){for(let j=0;j<55;j++){let yy=14.9-j*.24,zz=z+Math.sin(j*.7)*.36;for(let k=0;k<3;k++)b(s*(18.75+rnd()*.22),yy+(rnd()-.5)*.22,zz+(rnd()-.5)*.65,.22,.2,.3,[C.leaf,'#839658',C.green][Math.floor(rnd()*3)],shell)}}for(let x of [s*6.3,s*8.8,s*12.8,s*17.6])ivy(x,17,13.87,13,.6,shell)}
  for(let x of [-15,-10,-5,5,10,15]){b(x,6.3,13.85,3.4,.4,.75,C.wood2,shell);for(let j=0;j<36;j++){let xx=x+(rnd()-.5)*3.2,yy=6.66+rnd()*.6,zz=13.87+rnd()*.65;b(xx,yy,zz,.25,.24,.27,C.leaf,shell);if(j%3===0){let flower=j%2?'#af93c7':'#eee1c5';for(let s of [-1,1])b(xx+s*.075,yy+.1,zz,.16,.11,.19,flower,shell)}}}
  // Terrace details belong to the library: benches, lamp pedestals, paving border.
  for(let x of [-15,15]){b(x,1.35,16.2,3.3,.16,.85,C.wood2);for(let j=0;j<5;j++)b(x,1.99+j*.12,15.84,3.3,.085,.13,C.wood);for(let xx of [-1.24,1.24]){b(x+xx,1.03,16.2,.22,.56,.65,C.shade);b(x+xx,1.75,16.1,.2,.78,.3,C.wood)}planter(x-2.6,16,.7,1.4);planter(x+2.6,16,.7,1.4)}
  for(let x=-23;x<=23;x+=1){b(x,.15,17.2,.76,.23,.11,C.shade);b(x,.34,17.24,.95,.08,.14,C.light)}for(let s of [-1,1])for(let z=-18;z<17;z+=1){b(s*24.23,.18,z,.12,.26,.82,C.shade);b(s*24.27,.43,z,.12,.09,.96,C.light)}
  // Coherent interior ornament: column fluting, capitals, arch ribs, and balcony coffers.
  for(let x of [-8.2,8.2])for(let z of [-12,-6,0,6,11]){for(let sx of [-1,1])for(let sz of [-1,1])b(x+sx*.32,10.1,z+sz*.32,.095,17.6,.095,C.light,inside);for(let y of [1.65,7.9,14.9,19.5]){for(let d of [.56,.72]){b(x,y+.16,z,d*2,.11,d*2,C.shade,inside)}for(let j=0;j<8;j++){let a=j*Math.PI/4;b(x+Math.cos(a)*.58,y+.45,z+Math.sin(a)*.58,.22,.32,.22,oak,inside)}}for(let y of [4.1,11.1,18.1]){b(x,y,z+.4,.25,.3,.16,C.gold,inside,'metal');lantern(x,y+.65,z+.63,.48,false,inside)}}
  for(let y of [7.5,14.5])for(let s of [-1,1]){b(s*8.16,y,-1.5,.13,.1,26,oak,inside);b(s*8.1,y-.2,-1.5,.16,.12,26,C.gold,inside);for(let z=-13;z<11;z+=1.2){b(s*8.35,y-.36,z,.48,.56,.35,C.wood2,inside);b(s*8.5,y-.67,z,.28,.2,.25,oak,inside)}for(let z=-13;z<=11;z+=.8){for(let k=0;k<4;k++)b(s*8.02,y+.7+k*.11,z,.21-k*.035,.12,.21-k*.035,C.wood2,inside)}}
  // Carved arches beneath the galleries and inset panels on the rear balcony soffits.
  for(let y of [7.9,14.9]){
    for(let s of [-1,1])for(let [za,zb] of [[-12,-6],[-6,0],[0,6],[6,11]])for(let j=0;j<=40;j++){
      let t=j/40,z=za+(zb-za)*t,yy=y-2.8+Math.sqrt(Math.max(0,1-(2*t-1)**2))*2;
      b(s*8.18,yy,z,.35,.22,.19,C.wood2,inside);b(s*7.98,yy+.13,z,.08,.09,.17,C.gold,inside);
    }
    for(let x=-7.2;x<=7.3;x+=2.4)for(let z of [-14.6,-12.8]){
      b(x,y-.47,z,2.13,.04,1.5,C.wood2,inside);
      for(let s of [-1,1]){b(x+s*1.1,y-.51,z,.055,.075,1.65,oak,inside);b(x,y-.51,z+s*.79,2.23,.075,.055,oak,inside)}
      b(x,y-.52,z,.19,.035,.19,C.gold,inside);
    }
    for(let j=0;j<=90;j++){let x=-8.1+j*.18,yy=y-3.05+Math.sqrt(Math.max(0,1-(x/8.1)**2))*2.25;b(x,yy,-11.33,.2,.24,.3,C.wood2,inside);b(x,yy+.14,-11.12,.19,.07,.065,C.gold,inside)}
  }
  // The rear window has the same layered tracery as the main façade, visible from within.
  const rear=panel(0,-15.99,0,shell);
  for(let [x,h] of [[-4.12,13.3],[-1.38,16.1],[1.38,16.1],[4.12,13.3]]){
    const r=1.29,base=1.45,spring=base+h-Math.sqrt(3)*r;
    for(let s of [-1,1])rear(x+s*r,base+(spring-base)/2,.22,.075,spring-base,.08,C.gold);
    for(let xx=-r;xx<=r;xx+=.09)rear(x+xx,archY(xx,r,spring),.22,.11,.11,.1,C.gold);
    for(let y=2;y<spring;y+=1.2)rear(x,y,.24,2.55,.045,.08,C.gold);
  }
  rosette(rear,0,17.2,.27,1.34);rosette(rear,-2.76,13.2,.27,.7);rosette(rear,2.76,13.2,.27,.7);
  for(let x of [-6.65,6.65])banner(x,-11.02,12.65,1.35,6.4,0,inside);
  for(let y of [7.9,14.9])for(let x of [-6.9,6.9]){rear(x,y+2.1,.4,.09,3.7,.18,C.gold);for(let j=0;j<12;j++)rear(x,y+2.7+j*.1,.5,.23-j*.012,.09,.14,C.bright)}
  // Coffered planks on upper galleries and warm carpet borders.
  for(let y of [7.91,14.91]){for(let s of [-1,1])for(let x=8.4;x<17.8;x+=.36)for(let z=-15;z<12;z+=2.15){if(s>0&&x>12.05&&x<14.75&&z>-4.2&&z<10.3)continue;b(s*x,y,z,.34,.028,2.08,[C.wood2,C.wood,oak][Math.floor(rnd()*3)],inside)}for(let s of [-1,1]){b(s*10.1,y+.025,-1.5,1.25,.024,26,C.blue,inside);for(let side of [-1,1])b(s*10.1+side*.54,y+.04,-1.5,.04,.013,26,C.gold,inside)}}
  // Additional reading niches on the galleries; remain outside the walking path.
  for(let y of [7.9,14.9])for(let z of [-9,1]){b(-15,y+.5,z,2.2,.25,1.1,C.wood,inside);b(-15,y+.68,z,2.2,.16,1.05,C.blue,inside);b(-15,y+1.17,z-.49,2.24,.95,.15,C.wood2,inside);for(let k=-2;k<=2;k++)b(-15+k*.42,y+1.2,z-.38,.36,.5,.18,C.blue,inside);b(-15.05,y+.88,z+.14,.55,.12,.36,C.paper,inside);solid(-15,z,2.2,1.3,y<10?1:2)}
  // Ornamental ceiling ribs and repeated star bosses.
  for(let z of [-12,-6,0,6,11]){for(let j=0;j<82;j++){let x=-8.1+j*.2,y=archY(x,8.2,9.2);b(x,y-.22,z-.22,.18,.19,.14,oak,inside);b(x,y+.22,z+.18,.15,.16,.14,C.gold,inside)}b(0,23.43,z,.72,.16,.72,C.wood,inside);for(let sx of [-1,1])for(let sz of [-1,1])b(sx*.21,23.31,z+sz*.21,.13,.12,.13,C.gold,inside)}
  // Hanging candle chains, chandelier finials and curled brass arms.
  for(let z of [-7,4]){for(let y=16;y<22;y+=.21){b(-.08,y,z,.15,.11,.04,C.gold,inside,'metal');b(.08,y+.09,z,.04,.11,.15,C.gold,inside,'metal')}for(let rr of [2.8,1.82]){let yy=rr>2?15.9:14.4;for(let k=0;k<10;k++){let a=k*Math.PI/5,x=Math.cos(a)*rr,zz=z+Math.sin(a)*rr;for(let t=0;t<12;t++){let q=t/12;b(x*(1-.22*q),yy-.2+Math.sin(q*Math.PI)*.3,zz+(z-zz)*.22*q,.07,.08,.07,C.bright,inside,'metal')}b(x,yy+.08,zz,.31,.09,.31,C.gold,inside);b(x,yy+.74,zz,.06,.14,.06,'#fff1b2',inside,'glow')}}for(let j=0;j<6;j++)b(0,13.85-j*.13,z,.6-j*.085,.14,.6-j*.085,C.gold,inside,'metal')}
  // Detailed staircase newel posts and embroidered runners.
  for(let y0 of [.9,7.9])for(let i=0;i<35;i++){let z=10-(i+.5)*.4,y=y0+(i+1)*.2;for(let x of [12.24,14.76]){b(x,y+.95,z,.18,.18,.18,oak,inside);b(x,y+1.15,z,.16,.12,.16,C.gold,inside)}for(let s of [-1,1]){b(13.5+s*.83,y+.047,z,.035,.012,.39,C.gold,inside);b(13.5+s*.7,y+.052,z,.035,.012,.1,C.bright,inside)}if(i%4===0){for(let sx of [-1,1])for(let sz of [-1,1])b(13.5+sx*.12,y+.048,z+sz*.08,.07,.012,.05,C.gold,inside)}}
  // Library catalog desk and cabinet: handles, drawers, a ledger, and task light.
  b(-12.4,1.45,10.5,4.2,1.1,1.18,C.wood,inside);b(-12.4,2.08,10.5,4.55,.18,1.48,C.wood2,inside);for(let i=0;i<8;i++)for(let j=0;j<3;j++){b(-14.15+i*.5,1.12+j*.28,11.15,.43,.22,.06,oak,inside);b(-14.15+i*.5,1.12+j*.28,11.21,.12,.065,.07,C.gold,inside,'metal')}b(-12.1,2.23,10.5,1.2,.17,.72,C.paper,inside);lantern(-14.05,2.52,10.4,.65,false,inside);solid(-12.4,10.5,4.55,1.5,0);
  // Leaning library ladders: each rung and wheel is modelled, with a matching footprint.
  for(let [level,y,z] of [[0,.9,.6],[1,7.9,-12.7]]){
    for(let side of [-1,1])for(let j=0;j<36;j++){let t=j/35;b(-15.48-t*1.17,y+.25+t*5.35,z+side*.47,.1,.18,.12,C.wood2,inside)}
    for(let j=0;j<13;j++){let t=j/12;b(-15.48-t*1.17,y+.25+t*5.35,z,.14,.09,.95,oak,inside);b(-15.36-t*1.17,y+.28+t*5.35,z,.035,.03,.94,C.gold,inside)}
    for(let side of [-1,1]){b(-15.47,y+.13,z+side*.5,.19,.22,.17,C.dark,inside);b(-16.64,y+5.75,z+side*.5,.13,.3,.14,C.gold,inside,'metal')}
    solid(-16.02,z,1.5,1.15,level);
  }
  // Fine blue-and-gold tile mosaic; even the central floor is readable close up.
  for(let z=-12;z<=11;z+=.48)for(let s of [-1,1]){b(s*1.28,.959,z,.07,.012,.14,C.gold,inside);b(s*1.14,.959,z+.12,.06,.012,.07,C.bright,inside)}for(let z of [-9,-2,5,10])for(let k=0;k<16;k++){let a=k*Math.PI/8;b(Math.cos(a)*1.08,.963,z+Math.sin(a)*1.08,.05,.008,.06,C.gold,inside)}
  // Leaf clusters grow around balcony planters and the edges of the rear window.
  for(let y of [7.9,14.9])for(let s of [-1,1])for(let z of [-10,-5,0,5,10]){b(s*8.35,y+.56,z,1.2,.42,.56,C.wood2,inside);for(let j=0;j<15;j++){let x=s*8.3+(rnd()-.5)*.65,zz=z+(rnd()-.5)*1.1,yy=y+.85+rnd()*.4;b(x,yy,zz,.18,.21,.19,C.leaf,inside);if(j%5===0)b(x,yy+.13,zz,.13,.11,.14,j%2?'#ac8ac1':C.paper,inside)}}
}
